"""Keep the offers and the recipe pool current, without anyone running a command.

Offers change at the start of each week, and recipes are only worth planning
if they use this week's offers. So once a week, per branch that any user has
as a home market:

1. fetch, clean, translate and classify the offers, and load them — unless
   this week's are already loaded;
2. for every diet any user has (and "normal"), check how many recipes are
   *usable* — they fit the diet and use enough of this week's offers
   (planner.DEFAULT_MIN_OFFERS) — and fetch more from Spoonacular only where
   the pool is short.

`ensure_pool` is also what a request calls when one user's own filters
(allergens, ingredients they don't eat, recipes already suggested) leave too
little: the same search, with those filters passed to Spoonacular too.

Spoonacular's quota is finite, so every search is recorded (RecipeFetch) and
capped per week; asking the same question again pages past what it already
returned. The scheduler that runs this on Mondays is app/scheduler.py; the
CLI is `cheaprecipe weekly`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cheaprecipe import vocabulary
from cheaprecipe.agents import planner
from cheaprecipe.calculation.diet import fits, ingredient_diet
from cheaprecipe.calculation.families import in_family, members
from cheaprecipe.db.adapters import (
    STORE_TZ,
    allergen_free,
    avoids,
    current_offers,
    offer_items,
    recipe_candidate,
)
from cheaprecipe.db.load import (
    STORE_NAMES,
    LoadReport,
    chain_of,
    load_offers,
    load_recipes,
    relink_recipes,
)
from cheaprecipe.db.models import (
    Address,
    Offer,
    RecipeCache,
    RecipeFetch,
    Supermarket,
    UserPreference,
    user_home_market,
)
from cheaprecipe.ingestion import aldi, edeka
from cheaprecipe.matching import retrieval
from cheaprecipe.matching.offers import is_kind_of

log = logging.getLogger(__name__)

# A diet's pool is "short" below this many usable recipes: enough for a
# week of five meals with room for a refine to swap some.
MIN_USABLE = 8
# Recipes asked for per search.
FETCH_NUMBER = 40
# Spoonacular calls the app may make on its own, per store per week, and per
# identical question — a guard on the quota, not a target.
MAX_FETCHES_PER_WEEK = 24
MAX_FETCHES_PER_QUERY = 3

# Our allergens -> Spoonacular's `intolerances` values. Celery, mustard and
# lupin have no equivalent: they are filtered locally only (db/adapters.py).
INTOLERANCES = {
    "gluten": "gluten",
    "crustaceans": "shellfish",
    "molluscs": "shellfish",
    "eggs": "egg",
    "fish": "seafood",
    "peanuts": "peanut",
    "soy": "soy",
    "milk": "dairy",
    "nuts": "tree nut",
    "sesame": "sesame",
    "sulphites": "sulfite",
}


def week_start(now: datetime | None = None) -> date:
    """Monday of the current offer week, German time."""
    today = (now or datetime.now(STORE_TZ)).astimezone(STORE_TZ).date()
    return today - timedelta(days=today.weekday())


def default_store_id(store: str) -> str:
    return edeka.DEFAULT_MARKET_ID if store == "edeka" else aldi.DEFAULT_CATEGORY_ID


def _chain_id(session: Session, store: str) -> int | None:
    return session.scalar(
        select(Supermarket.id).where(Supermarket.name == STORE_NAMES.get(store, store.upper()))
    )


# --- offers ---------------------------------------------------------------------------

def _branch_id(session: Session, store_id: str) -> int | None:
    return session.scalar(select(Address.id).where(Address.market_id == store_id))


def offers_loaded(session: Session, store: str, store_id: str | None = None) -> bool:
    """Whether this week's offers for the branch are already in the database."""
    branch = _branch_id(session, store_id or default_store_id(store))
    if branch is None:
        return False
    return bool(
        session.scalar(
            select(func.count())
            .select_from(Offer)
            .where(Offer.address_id == branch, Offer.valid_from >= week_start())
        )
    )


def markets_in_use(session: Session) -> list[Address]:
    """Every branch some user has as a home market — what the refresh covers."""
    return list(
        session.scalars(
            select(Address).where(Address.id.in_(select(user_home_market.c.address_id))).order_by(Address.id)
        )
    )


def target_key(branch: Address) -> str:
    """The branch's name in WeeklyRefresh: "<chain>:<market id>"."""
    return f"{chain_of(branch)}:{branch.market_id}"


def refresh_offers(session: Session, store: str, store_id: str | None = None) -> LoadReport:
    """Run the offers pipeline (fetch → clean → translate → classify) and load it."""
    from cheaprecipe import pipeline  # the pipeline imports db code; keep it lazy

    store_id = store_id or default_store_id(store)
    frame = pipeline.build_offers(store=store, store_id=store_id)
    report = LoadReport()
    offers = load_offers(session, frame, store, store_id, report)
    relink_recipes(session, offers)  # the pool's recipes, against this week's offers
    session.commit()
    return report


# --- the recipe pool -------------------------------------------------------------------

@dataclass(frozen=True)
class PoolFilter:
    """What a recipe must satisfy to be usable for someone."""

    diet: str = "normal"
    allergens: frozenset[str] = frozenset()
    dislikes: tuple[str, ...] = ()
    exclude_ids: frozenset[int] = frozenset()
    # "breakfast" or "main"; None: any course.
    course: str | None = None

    def query_key(self) -> str:
        intolerances = sorted({INTOLERANCES[a] for a in self.allergens if a in INTOLERANCES})
        parts = [self.diet, ",".join(intolerances), ",".join(sorted(self.dislikes))]
        if self.course == "breakfast":
            parts.append("breakfast")
        return "|".join(parts)[:500]

    def fits_course(self, row: RecipeCache) -> bool:
        """A recipe of unknown course counts as a main, as the planner plans it."""
        if self.course is None:
            return True
        return (row.course == "breakfast") == (self.course == "breakfast")


def usable_count(session: Session, offers: list[Offer], wanted: PoolFilter) -> int:
    """Recipes in the pool that fit `wanted` and use enough of `offers`."""
    offered = {o.canonical_ingredient_id for o in offers if o.canonical_ingredient_id}
    rows = [
        row
        for row in session.scalars(select(RecipeCache))
        if row.id not in wanted.exclude_ids
        and wanted.fits_course(row)
        and fits(row.diet_type, wanted.diet)
        and allergen_free(row, set(wanted.allergens))
        and avoids(row, list(wanted.dislikes))
    ]
    candidates = [recipe_candidate(row, offered) for row in rows]
    return len(planner.using_offers(candidates, offer_items(offers)))


@dataclass
class FetchResult:
    fetched: bool = False
    returned: int = 0
    added: int = 0
    skipped_reason: str | None = None


def _fetches(session: Session, store: str, key: str | None = None) -> list[RecipeFetch]:
    query = select(RecipeFetch).where(
        RecipeFetch.store == store, RecipeFetch.week_start == week_start()
    )
    if key is not None:
        query = query.where(RecipeFetch.query_key == key)
    return list(session.scalars(query))


def excluded_ingredients(dislikes: tuple[str, ...]) -> list[str]:
    """What a search leaves out: each disliked word, and its family's members
    ("pork" is also bacon, ham, sausage… — calculation/families.py)."""
    return list(dict.fromkeys(w for d in dislikes for w in [d, *members(d)]))


# Offers no recipe search should mention: nobody cooks with gummies.
NOT_SEARCHED = frozenset({"snack_or_sweet", "drink", "convenience", "pantry"})
# Searches one top-up may make: one per protein, cheapest proteins first,
# stopping as soon as the pool is big enough.
MAX_SEARCHES_PER_TOP_UP = 3


def _search_name(offer: Offer) -> str | None:
    """The name a recipe site knows the offer by (classify.py's base_ingredient)."""
    return offer.base_ingredient or offer.ingredient_en


def searches(offers: list[Offer], wanted: PoolFilter) -> list[tuple[str, list[str]]]:
    """The recipe searches worth making for these offers: (label, ingredients).

    Spoonacular's includeIngredients is an OR that ranks by how many are used,
    so one search over every offer is swamped by the many small things on
    sale and misses the few that make a dinner. A main is searched per
    protein on offer, by the name recipes use for it ("pork shoulder" for the
    marinated neck steaks); a breakfast by what breakfasts are made of. Offers
    classified before meal roles existed are searched as they were: all of
    them, cheapest first.
    """
    by_price = sorted(offers, key=lambda o: o.price)
    if not any(o.meal_role for o in offers):
        names = list(dict.fromkeys(n for o in by_price if (n := o.ingredient_en)))
        return [("offers", names)] if names else []

    def disliked(name: str) -> bool:
        return any(is_kind_of(name, d) or in_family(name, d) for d in wanted.dislikes)

    def names(*roles: str, fits_diet: bool = False) -> list[str]:
        found = [
            _search_name(o) for o in by_price
            if o.can_cook and o.meal_role in roles and _search_name(o)
            and not disliked(_search_name(o))
            and (not fits_diet or fits(ingredient_diet(_search_name(o)), wanted.diet))
        ]
        return list(dict.fromkeys(found))

    if wanted.course == "breakfast":
        breakfast = names("dairy", "fruit", "carb") + [n for n in names("protein") if "egg" in n]
        return [("breakfast", breakfast[:5])] if breakfast else []
    proteins = names("protein", fits_diet=True)
    if proteins:
        return [(protein, [protein]) for protein in proteins]
    vegetables = names("vegetable")
    return [("vegetables", vegetables[:5])] if vegetables else []


def fetch_recipes(
    session: Session, store: str, offers: list[Offer], wanted: PoolFilter, reason: str,
    minimum: int = 0,
) -> FetchResult:
    """Spoonacular searches for `wanted`, loaded into the pool — within the caps.

    One search per protein on offer (`searches`), those asked least this week
    first, up to MAX_SEARCHES_PER_TOP_UP, stopping once `minimum` recipes are
    usable. Asking the same question again pages past what it returned.
    """
    planned = searches(offers, wanted)
    if not planned:
        return FetchResult(skipped_reason="nothing on offer to search recipes for")
    base_key = wanted.query_key()
    asked = {label: _fetches(session, store, f"{base_key}|{label}"[:500]) for label, _ in planned}
    # Least asked first; among equals, the cheapest protein (the list's order).
    planned.sort(key=lambda search: len(asked[search[0]]))

    result = FetchResult()
    for label, ingredients in planned[:MAX_SEARCHES_PER_TOP_UP]:
        if len(_fetches(session, store)) >= MAX_FETCHES_PER_WEEK:
            result.skipped_reason = f"weekly cap of {MAX_FETCHES_PER_WEEK} searches reached"
            break
        earlier = asked[label]
        if len(earlier) >= MAX_FETCHES_PER_QUERY:
            continue
        key = f"{base_key}|{label}"[:500]
        offset = sum(f.returned for f in earlier)
        recipes = retrieval.complex_search(
            ingredients,
            number=FETCH_NUMBER,
            diet=vocabulary.spoonacular_diet(wanted.diet),
            intolerances=sorted({INTOLERANCES[a] for a in wanted.allergens if a in INTOLERANCES}) or None,
            exclude_ingredients=excluded_ingredients(wanted.dislikes) or None,
            dish_type="breakfast" if wanted.course == "breakfast" else "main course",
            offset=offset,
        )
        before = session.scalar(select(func.count()).select_from(RecipeCache))
        load_recipes(session, recipes, offers)
        added = session.scalar(select(func.count()).select_from(RecipeCache)) - before
        session.add(RecipeFetch(
            store=store, week_start=week_start(), query_key=key, reason=reason,
            offset=offset, returned=len(recipes), added=added,
        ))
        session.commit()
        log.info("fetched recipes for %s (%s) on %s: %d returned, %d new (offset %d)",
                 key, reason, ", ".join(ingredients), len(recipes), added, offset)
        result.fetched = True
        result.returned += len(recipes)
        result.added += added
        if minimum and usable_count(session, offers, wanted) >= minimum:
            break
    if not result.fetched and result.skipped_reason is None:
        result.skipped_reason = f"asked {MAX_FETCHES_PER_QUERY} times already this week"
    return result


def ensure_pool(
    session: Session,
    store: str,
    wanted: PoolFilter,
    reason: str = "top-up",
    minimum: int = MIN_USABLE,
    offers: list[Offer] | None = None,
) -> FetchResult:
    """Fetch recipes for `wanted` if fewer than `minimum` are usable; else do nothing."""
    offers = offers if offers is not None else current_offers(
        session, supermarket_id=_chain_id(session, store)
    )
    if not offers:
        return FetchResult(skipped_reason="no current offers")
    have = usable_count(session, offers, wanted)
    if have >= minimum:
        return FetchResult(skipped_reason=f"{have} usable already")
    log.info("pool short for %s: %d usable, want %d", wanted.query_key(), have, minimum)
    try:
        return fetch_recipes(session, store, offers, wanted, reason, minimum=minimum)
    except Exception as exc:  # noqa: BLE001 — quota, network: plan with what there is
        session.rollback()
        log.warning("recipe fetch for %s failed: %s", wanted.query_key(), exc)
        return FetchResult(skipped_reason=f"fetch failed: {exc}")


# --- the whole weekly run -------------------------------------------------------------------

@dataclass
class RefreshSummary:
    offers: str = "already loaded"
    pools: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"offers": self.offers, "pools": self.pools}


def diets_in_use(session: Session) -> list[str]:
    """Every diet a user has, plus "normal" (users with none, and new sign-ups)."""
    diets = {d for d in session.scalars(select(UserPreference.diet_type)) if d}
    return sorted(diets | {"normal"})


def weekly_refresh(
    session: Session, store: str = "edeka", store_id: str | None = None, force: bool = False
) -> RefreshSummary:
    """One branch's offers for this week loaded, and a usable pool for every diet in use."""
    store_id = store_id or default_store_id(store)
    summary = RefreshSummary()
    if force or not offers_loaded(session, store, store_id):
        report = refresh_offers(session, store, store_id)
        summary.offers = f"{report.offers_added} added, {report.offers_updated} updated"
    branch = _branch_id(session, store_id)
    offers = current_offers(session, [branch]) if branch is not None else []
    for diet in diets_in_use(session):
        result = ensure_pool(session, store, PoolFilter(diet=diet), reason="weekly", offers=offers)
        summary.pools[diet] = (
            f"{result.added} new of {result.returned}" if result.fetched else result.skipped_reason
        )
    log.info("weekly refresh %s:%s: %s", store, store_id, summary.as_dict())
    return summary
