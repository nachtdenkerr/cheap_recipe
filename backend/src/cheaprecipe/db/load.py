"""Pipeline files -> database: what `cheaprecipe load` does.

The pipeline stops at files (data/<store>_offers_classified.csv and
data/<store>_recipes.json); the API reads the database. This module is the
step between, and it is safe to run again: offers are upserted on
uq_offer_run (branch, title, valid_from) and recipes on uq_recipe_source
(source, Spoonacular id), so re-loading a week updates rows instead of
duplicating them.

The part that matters most is the link. The API's recipe page and shopping
list join recipe lines to offers through `canonical_ingredient_id`, while the
planner matches them by name (matching/offers.py). The load resolves every
recipe line with that same matcher and stores the result, so the price on
the page and the price the plan used cannot disagree:

- each offer gets the canonical ingredient of its English name;
- a recipe line that matches an offer shares that offer's canonical id;
- any other line gets the canonical ingredient of its own name, so a line
  that matches an offer next week (same kind of thing) links up then.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from cheaprecipe.agents.contracts import Item
from cheaprecipe.calculation import cost
from cheaprecipe.calculation.allergens import allergens_of
from cheaprecipe.calculation.diet import recipe_diet
from cheaprecipe.db.adapters import STORE_TZ, base_of
from cheaprecipe.db.models import (
    Address,
    CanonicalIngredient,
    Cuisine,
    Offer,
    RecipeCache,
    RecipeIngredient,
    Supermarket,
)
from cheaprecipe.matching.index import course_of, is_meal, metric_quantity, recipe_times
from cheaprecipe.matching.offers import canonical, match_offer
from cheaprecipe.vocabulary import CUISINES

log = logging.getLogger(__name__)

# How each chain is named in the database.
STORE_NAMES = {"edeka": "EDEKA", "aldi": "ALDI SÜD"}


@dataclass
class LoadReport:
    offers_added: int = 0
    offers_updated: int = 0
    offers_skipped: int = 0
    recipes_added: int = 0
    recipes_updated: int = 0
    recipes_skipped: int = 0
    lines_on_offer: int = 0
    lines_total: int = 0

    def __str__(self) -> str:
        return (
            f"offers: {self.offers_added} added, {self.offers_updated} updated, "
            f"{self.offers_skipped} skipped; recipes: {self.recipes_added} added, "
            f"{self.recipes_updated} updated, {self.recipes_skipped} skipped; "
            f"{self.lines_on_offer}/{self.lines_total} recipe lines linked to an offer"
        )


# --- small conversions ----------------------------------------------------------

def _value(cell):
    """A CSV cell, with pandas' NaN as None."""
    if cell is None or (isinstance(cell, float) and math.isnan(cell)):
        return None
    return cell


def _flag(cell) -> bool | None:
    """The classifier's True/False columns, read as they come back from CSV."""
    cell = _value(cell)
    if cell is None:
        return None
    if isinstance(cell, str):
        return cell.strip().lower() == "true"
    return bool(cell)


def _date(cell) -> date | None:
    cell = _value(cell)
    if cell is None or pd.isna(cell):  # NaT, too: pandas' missing date
        return None
    return date.fromisoformat(str(cell)[:10])


def offer_week(today: date | None = None) -> tuple[date, date]:
    """Monday and Saturday of the offer week `today` is in, German time."""
    today = today or datetime.now(STORE_TZ).date()
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=5)


def _canonical_row(session: Session, name: str, cache: dict[str, CanonicalIngredient]):
    """Get or create the canonical ingredient named `canonical(name)`."""
    key = canonical(name)[:120]
    if not key:
        return None
    row = cache.get(key)
    if row is None:
        row = session.scalars(
            select(CanonicalIngredient).where(CanonicalIngredient.name == key)
        ).first()
        if row is None:
            row = CanonicalIngredient(name=key)
            session.add(row)
        # From the name, every load, so a fix to calculation/allergens.py
        # reaches rows loaded before it.
        row.allergens = sorted(allergens_of(key))
        cache[key] = row
    return row


# --- offers ---------------------------------------------------------------------------

def _branch(session: Session, store: str, store_id: str) -> Address:
    name = STORE_NAMES.get(store, store.upper())
    chain = session.scalars(select(Supermarket).where(Supermarket.name == name)).first()
    if chain is None:
        chain = Supermarket(name=name)
        session.add(chain)
    branch = session.scalars(select(Address).where(Address.market_id == store_id)).first()
    if branch is None:
        branch = Address(market_id=store_id, supermarket=chain)
        session.add(branch)
    return branch


def upsert_market(session: Session, info) -> Address:
    """The Address for a found market (ingestion/markets.MarketInfo), details refreshed."""
    branch = _branch(session, info.chain, info.market_id)
    branch.name = info.name
    branch.street = info.street
    branch.postal_code = info.postal_code
    branch.city = info.city
    return branch


def chain_of(branch: Address) -> str:
    """The store key ("edeka", "aldi") of a branch, from its chain's name."""
    name = branch.supermarket.name if branch.supermarket else None
    return next((key for key, label in STORE_NAMES.items() if label == name), "edeka")


def load_offers(
    session: Session,
    frame: pd.DataFrame,
    store: str,
    store_id: str,
    report: LoadReport | None = None,
    canonicals: dict[str, CanonicalIngredient] | None = None,
    fetched_on: date | None = None,
) -> list[Offer]:
    """Upsert a classified offers frame; returns the offers now in the database.

    Offers the classifier marked as not for cooking (non-food, drinks) are
    skipped: nothing plans with them.

    An offer with no dates at all is valid for the offer week it was fetched
    in (`fetched_on`, default today): ALDI SÜD's weekly-offers page carries no
    dates, being by definition this week's.
    """
    week = offer_week(fetched_on)
    report = report or LoadReport()
    canonicals = canonicals if canonicals is not None else {}
    branch = _branch(session, store, store_id)
    session.flush()

    loaded = []
    for row in frame.to_dict("records"):
        title = _value(row.get("title"))
        price = _value(row.get("price"))
        if not title or price is None or _flag(row.get("can_cook")) is not True:
            report.offers_skipped += 1
            continue
        valid_from = _date(row.get("validFrom"))
        valid_till = _date(row.get("validTill"))
        if valid_from is None and valid_till is None:
            valid_from, valid_till = week
        offer = session.scalars(
            select(Offer).where(
                Offer.address_id == branch.id,
                Offer.title == title,
                Offer.valid_from == valid_from,
            )
        ).first()
        if offer is None:
            offer = Offer(address=branch, title=title, valid_from=valid_from, price=price)
            session.add(offer)
            report.offers_added += 1
        else:
            report.offers_updated += 1

        ingredient = _value(row.get("ingredient_en"))
        offer.price = float(price)
        offer.category = _value(row.get("category"))
        offer.description = _value(row.get("descriptions"))
        offer.valid_till = valid_till
        offer.quantity_amount = _value(row.get("quantity_amount"))
        offer.quantity_unit = _value(row.get("quantity_unit"))
        offer.quantity_basis = _value(row.get("quantity_basis"))
        pack_count = _value(row.get("pack_count"))
        offer.pack_count = int(pack_count) if pack_count is not None else None
        offer.deposit = _value(row.get("deposit"))
        offer.price_per_unit = _value(row.get("price_per_unit"))
        offer.price_per_unit_unit = _value(row.get("price_per_unit_unit"))
        offer.ingredient_en = ingredient
        offer.can_cook = True
        offer.use_baking = _flag(row.get("use_baking"))
        offer.use_drinks = _flag(row.get("use_drinks"))
        offer.meal_role = _value(row.get("meal_role"))
        base = _value(row.get("base_ingredient"))
        offer.base_ingredient = str(base).strip().lower()[:120] if base else None
        offer.canonical_ingredient = (
            _canonical_row(session, ingredient, canonicals) if ingredient else None
        )
        loaded.append(offer)

    session.flush()
    return loaded


# --- recipes --------------------------------------------------------------------------

def _match_items(offers: list[Offer]) -> list[Item]:
    """The offers as the matcher's Items, keyed back by offer id.

    Only name and id matter for matching; the prices are carried along so
    the Items are valid, not because anything here prices with them.
    """
    items = []
    for offer in offers:
        quantity = cost.quantity_of(offer.quantity_amount, offer.quantity_unit)
        if not offer.ingredient_en or quantity is None:
            continue
        per_unit = cost.unit_of(offer.price_per_unit_unit)
        items.append(
            Item(
                name=offer.ingredient_en,
                quantity=quantity,
                price=offer.price,
                price_per_unit=offer.price_per_unit or offer.price,
                price_per_unit_unit=per_unit[0] if per_unit else quantity.unit,
                offer_id=offer.id,
                base=base_of(offer),
            )
        )
    return items


_TAGS = re.compile(r"<[^>]+>")


def _steps(recipe: dict) -> str | None:
    """Method steps, one per line — how the API splits them back out."""
    steps = [
        step["step"].strip()
        for block in recipe.get("analyzedInstructions") or []
        for step in block.get("steps") or []
        if step.get("step", "").strip()
    ]
    if steps:
        return "\n".join(steps)
    text = _TAGS.sub("\n", recipe.get("instructions") or "")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines) or None


def _cuisine(session: Session, recipe: dict, cache: dict[str, Cuisine]) -> Cuisine | None:
    name = next((c for c in recipe.get("cuisines") or [] if c in CUISINES), None)
    if name is None:
        return None
    if name not in cache:
        row = session.scalars(select(Cuisine).where(Cuisine.name == name)).first()
        cache[name] = row or Cuisine(name=name)
        session.add(cache[name])
    return cache[name]


def load_recipes(
    session: Session,
    recipes: list[dict],
    offers: list[Offer],
    report: LoadReport | None = None,
    canonicals: dict[str, CanonicalIngredient] | None = None,
) -> list[RecipeCache]:
    """Upsert Spoonacular recipes and link their lines to `offers`.

    Skips what cannot be planned: recipes that are not a meal (dishTypes),
    and lines with no amount ("1 serving"); a recipe left with no lines is
    skipped too, as parse_recipe_json does.
    """
    report = report or LoadReport()
    canonicals = canonicals if canonicals is not None else {}
    by_id = {offer.id: offer for offer in offers}
    items = _match_items(offers)
    cuisines: dict[str, Cuisine] = {}

    loaded = []
    for recipe in recipes:
        lines = []
        for ingredient in recipe.get("extendedIngredients") or []:
            quantity = metric_quantity(ingredient)
            if quantity is not None:
                lines.append((ingredient["name"], quantity))
        if not is_meal(recipe) or not lines:
            report.recipes_skipped += 1
            continue

        external_id = str(recipe["id"])
        row = session.scalars(
            select(RecipeCache).where(
                RecipeCache.source == "spoonacular", RecipeCache.external_id == external_id
            )
        ).first()
        if row is None:
            row = RecipeCache(source="spoonacular", external_id=external_id, name=recipe["title"])
            session.add(row)
            report.recipes_added += 1
        else:
            report.recipes_updated += 1

        preparation, cooking = recipe_times(recipe)
        row.name = recipe["title"]
        row.image_url = recipe.get("image")
        row.servings = recipe.get("servings")
        # From every ingredient Spoonacular listed, not only the ones kept:
        # a line with no amount can still be the beef.
        row.diet_type = recipe_diet(
            [i["name"] for i in recipe.get("extendedIngredients") or []], recipe
        )
        row.course = course_of(recipe) or row.course
        row.cooking_time = cooking
        row.total_time = (preparation or 0) + cooking
        steps = _steps(recipe)
        if steps != row.instructions:
            row.instructions, row.method_checked = steps, False
        row.cuisine = _cuisine(session, recipe, cuisines)

        row.ingredients = []
        for name, quantity in lines:
            item = match_offer(name, items)
            offer = by_id.get(item.offer_id) if item is not None else None
            if offer is not None and offer.canonical_ingredient is not None:
                linked = offer.canonical_ingredient
                report.lines_on_offer += 1
            else:
                linked = _canonical_row(session, name, canonicals)
            report.lines_total += 1
            row.ingredients.append(
                RecipeIngredient(
                    name=name,
                    amount=quantity.amount,
                    unit=quantity.unit,
                    canonical_ingredient=linked,
                )
            )
        loaded.append(row)

    session.flush()
    return loaded


def fill_instructions(session: Session, rows: list[RecipeCache]) -> int:
    """Fetch the method for recipes stored without one; returns how many got it.

    Recipes fetched before complexSearch was asked for instructions have none.
    One informationBulk call covers all of `rows` that need it — callers pass
    what is about to be shown, so the quota goes on recipes people look at,
    and each is fetched once. Raises what the request raises.
    """
    from cheaprecipe.matching import retrieval  # network; keep it out of plain loading

    missing = [r for r in rows if not r.instructions and r.source == "spoonacular" and r.external_id]
    if not missing:
        return 0
    found = {str(info["id"]): info for info in retrieval.information_bulk([r.external_id for r in missing])}
    filled = 0
    for row in missing:
        steps = _steps(found[row.external_id]) if row.external_id in found else None
        if steps:
            row.instructions = steps
            filled += 1
    session.commit()
    log.info("filled the method of %d/%d recipes", filled, len(missing))
    return filled


# Methods one editing call takes: a plan's recipes, or a page of them.
METHODS_PER_CALL = 8


def check_methods(session: Session, rows: list[RecipeCache]) -> int:
    """Run the method editor (agents/method.py) over methods not yet checked.

    Stores the clean steps and marks them checked, so each recipe is edited
    once. Returns how many were edited; raises what the model call raises.
    """
    from cheaprecipe.agents import method  # a model call; keep it out of plain loading

    pending = [r for r in rows if r.instructions and not r.method_checked]
    edited_count = 0
    for start in range(0, len(pending), METHODS_PER_CALL):
        batch = {r.name: r.instructions for r in pending[start:start + METHODS_PER_CALL]}
        edited = method.edit_methods(batch)
        for row in pending[start:start + METHODS_PER_CALL]:
            steps = edited.get(row.name)
            if steps:
                row.instructions, row.method_checked = "\n".join(steps), True
                edited_count += 1
        session.commit()
    return edited_count


def relink_recipes(session: Session, offers: list[Offer]) -> int:
    """Link every pooled recipe's lines to these offers, where one covers them.

    A recipe is linked when it is loaded, against that week's offers; new
    offers (next week's, or a branch just added) and better matching (an
    offer's base ingredient) only reach it through this. A line no offer
    covers keeps its link. Returns how many lines changed.
    """
    items = _match_items(offers)
    by_id = {offer.id: offer for offer in offers}
    changed = 0
    for row in session.scalars(select(RecipeCache)):
        for line in row.ingredients:
            item = match_offer(line.name, items)
            offer = by_id.get(item.offer_id) if item is not None else None
            if offer is None or offer.canonical_ingredient is None:
                continue
            if line.canonical_ingredient_id != offer.canonical_ingredient.id:
                line.canonical_ingredient = offer.canonical_ingredient
                changed += 1
    session.flush()
    log.info("relinked %d recipe lines to %d offers", changed, len(offers))
    return changed


# --- both, from the pipeline's files ----------------------------------------------------

def load_files(
    session: Session,
    offers_path: Path,
    recipes_path: Path | None,
    store: str,
    store_id: str,
) -> LoadReport:
    """Load a store's classified offers, then its recipes against them."""
    report = LoadReport()
    canonicals: dict[str, CanonicalIngredient] = {}
    frame = pd.read_csv(offers_path)
    offers = load_offers(session, frame, store, store_id, report, canonicals)
    if recipes_path is not None and recipes_path.exists():
        recipes = json.loads(recipes_path.read_text(encoding="utf-8"))
        load_recipes(session, recipes, offers, report, canonicals)
    elif recipes_path is not None:
        log.warning("%s does not exist; loaded offers only", recipes_path)
    relink_recipes(session, offers)
    session.commit()
    return report
