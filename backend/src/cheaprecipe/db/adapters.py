"""Database rows -> the agent layer's contracts, and the row-level filters.

Shared by the API (app/routers/generate.py) and the weekly refresh
(cheaprecipe/refresh.py), which both have to see the recipe pool the way the
planner will.
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from cheaprecipe.agents.contracts import Ingredient, Item, Recipe
from cheaprecipe.calculation import cost
from cheaprecipe.calculation.allergens import allergens_of
from cheaprecipe.calculation.families import in_family
from cheaprecipe.db.models import Address, Offer, RecipeCache
from cheaprecipe.matching.offers import is_kind_of
from cheaprecipe.vocabulary import CUISINES

log = logging.getLogger(__name__)

# Offer validity dates are the German stores' own calendar days.
STORE_TZ = ZoneInfo("Europe/Berlin")


def current_offers(
    session: Session,
    address_ids: list[int] | None = None,
    supermarket_id: int | None = None,
) -> list[Offer]:
    """Offers still valid today — at these branches, or of this chain, if given."""
    today = datetime.now(STORE_TZ).date()
    query = select(Offer).where(or_(Offer.valid_till.is_(None), Offer.valid_till >= today))
    if address_ids is not None:
        query = query.where(Offer.address_id.in_(address_ids))
    if supermarket_id is not None:
        query = query.join(Address).where(Address.supermarket_id == supermarket_id)
    return list(session.scalars(query))


def offer_items(offers: list[Offer]) -> list[Item]:
    """Offers as the planner's Items; ones it cannot measure are left out."""
    items = []
    for offer in offers:
        quantity = cost.quantity_of(offer.quantity_amount, offer.quantity_unit)
        ppu_unit = cost.unit_of(offer.price_per_unit_unit)
        if quantity is None or offer.price_per_unit is None or ppu_unit is None:
            continue  # the planner cannot price what it cannot measure
        items.append(
            Item(
                name=offer.ingredient_en or offer.title,
                quantity=quantity,
                price=offer.price,
                price_per_unit=offer.price_per_unit,
                price_per_unit_unit=ppu_unit[0],
                sale_start_date=offer.valid_from,
                offer_id=offer.id,
                base=base_of(offer),
            )
        )
    return items


def recipe_candidate(row: RecipeCache, offered: set[int]) -> Recipe:
    """A stored recipe as the planner's Recipe; `offered` are canonical ids on offer."""
    ingredients = []
    for line in row.ingredients:
        quantity = cost.quantity_of(line.amount, line.unit)
        if quantity is None:
            log.debug("recipe %s: skipping %r, unit %r", row.id, line.name, line.unit)
            continue
        ingredients.append(
            Ingredient(
                name=line.name,
                quantity=quantity,
                from_offer=line.canonical_ingredient_id in offered,
            )
        )
    return Recipe(
        name=row.name,
        ingredients=ingredients,
        cooking_instructions=row.instructions,
        servings=row.servings or 1,
        cooking_time=row.cooking_time or row.total_time or 0,
        cuisine=[row.cuisine.name] if row.cuisine and row.cuisine.name in CUISINES else [],
        total_kcal=row.total_kcal,
        kind=row.dish_kind,
        main_ingredient=row.main_ingredient,
        course=row.course,
        source=row.source,
        external_id=str(row.id),
    )


def avoids(row: RecipeCache, dislikes: list[str]) -> bool:
    """No line is anything the user does not eat (their black list).

    A line is out when it is a kind of the disliked word ("granny smith
    apples" for "apple"), or a member of the family it names ("Italian
    sausage" and "bacon" for "pork" — calculation/families.py).
    """
    return not any(
        is_kind_of(line.name, disliked) or in_family(line.name, disliked)
        for line in row.ingredients
        for disliked in dislikes
    )


# Offers whose base name is not something a recipe cooks with: a recipe's
# "cream cheese" is not the cream cheese spread.
NO_BASE_ROLES = frozenset({"convenience", "snack_or_sweet", "drink"})


def base_of(offer: Offer) -> str | None:
    """The name a recipe uses for the offer, when it is one to cook with."""
    return None if offer.meal_role in NO_BASE_ROLES else offer.base_ingredient


def allergen_free(row: RecipeCache, excluded: set[str]) -> bool:
    """Deterministic allergen filter — never the LLM.

    Both what the line is linked to and the line's own name are checked:
    either can be the one that says "walnuts".
    """
    if not excluded:
        return True
    return not any(
        excluded
        & (
            allergens_of(line.name)
            | set(line.canonical_ingredient.allergens or [] if line.canonical_ingredient else [])
        )
        for line in row.ingredients
    )
