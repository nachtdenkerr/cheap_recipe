"""ORM rows -> the response shapes in app/schemas.

The frontend's `Recipe` is richer than what the database stores, so part of it
is derived here from the plan (`Generation`) the recipe belongs to:

- an ingredient is on offer when an offer in the same plan resolves to the same
  canonical ingredient; anything else is shown as a pantry item;
- cost is the used share of each offer's pack, leftover the rest of the pack;
- nutrition and allergens come from the canonical ingredients.

The shopping list covers only the recipes the user added to their meal plan,
not everything the planner suggested.

Not stored anywhere yet, so returned empty: `summary` and `rationale`.
There is no regular price either — the chains publish only the offer price —
so the API makes no claim about savings.
"""

import math

from cheaprecipe.db.models import Generation, Offer, RecipeCache, User
from cheaprecipe.vocabulary import ALLERGENS, COMMON_DIETS, CUISINES
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.schemas.auth import User as UserOut
from app.schemas.recipes import Nutrition, RecipeCost
from app.schemas.recipes import Offer as OfferOut
from app.schemas.recipes import Recipe as RecipeOut
from app.schemas.recipes import RecipeIngredient as IngredientOut
from app.schemas.shopping import ShoppingListItem

# Unit -> (dimension, factor to grams or millilitres).
_UNITS = {
    "g": ("mass", 1.0),
    "kg": ("mass", 1000.0),
    "ml": ("volume", 1.0),
    "l": ("volume", 1000.0),
}


def _base(amount: float | None, unit: str | None) -> tuple[str, float] | None:
    """An amount in grams or millilitres with its dimension; None if unconvertible."""
    if amount is None or unit is None:
        return None
    known = _UNITS.get(unit.strip().lower())
    return (known[0], amount * known[1]) if known else None


def _cents(euros: float) -> int:
    return round(euros * 100)


def _format_amount(amount: float | None, unit: str | None) -> str:
    if amount is None:
        return unit or "to taste"
    return f"{amount:g} {unit}".strip() if unit else f"{amount:g}"


def _packs(needed: float | None, needed_unit: str | None, offer: Offer) -> float | None:
    """How many of `offer`'s packs (or price bases) `needed` is; None if unknown."""
    need = _base(needed, needed_unit)
    pack = _base(offer.quantity_amount, offer.quantity_unit)
    if need is None or pack is None or need[0] != pack[0] or pack[1] <= 0:
        return None
    return need[1] / pack[1]


# --- users --------------------------------------------------------------------

def user_out(user: User) -> UserOut:
    pref = user.preference
    diet = pref.diet_type if pref and pref.diet_type in COMMON_DIETS else "normal"
    return UserOut(
        name=user.fullname or user.username,
        email=user.email,
        diet_type=diet,
        household_size=(pref.household_size if pref else None) or 1,
        weekly_budget_cents=pref.weekly_budget_cents if pref else None,
        allergens=[a for a in ((pref.allergens if pref else None) or []) if a in ALLERGENS],
        market=pref.fav_supermarket.name if pref and pref.fav_supermarket else None,
        cuisines=[c for c in ((pref.cuisines if pref else None) or []) if c in CUISINES],
        white_list=list((pref.white_list if pref else None) or []),
        black_list=list((pref.black_list if pref else None) or []),
        health_goal=pref.health_goal if pref else None,
        age=pref.age if pref else None,
        gender=pref.gender if pref else None,
        week_time_availability=pref.week_time_availability if pref else None,
    )


# --- recipes ------------------------------------------------------------------

def offer_out(offer: Offer) -> OfferOut:
    return OfferOut(
        id=offer.id,
        title=offer.title,
        ingredient_en=offer.ingredient_en,
        category=offer.category,
        price_cents=_cents(offer.price),
        valid_from=offer.valid_from,
        valid_till=offer.valid_till,
    )


def latest_generation(session: Session, user: User) -> Generation | None:
    return session.scalars(
        select(Generation)
        .where(Generation.user_id == user.id)
        .order_by(Generation.created_at.desc(), Generation.id.desc())
        .limit(1)
    ).first()


def _plan_offers(generation: Generation) -> dict[int, Offer]:
    """The plan's offers keyed by canonical ingredient id."""
    return {
        item.offer.canonical_ingredient_id: item.offer
        for item in generation.items
        if item.offer is not None and item.offer.canonical_ingredient_id is not None
    }


def favourite_ids(user: User) -> set[int]:
    pref = user.preference
    return {recipe.id for recipe in pref.favourite_recipes} if pref else set()


def recipe_out(
    recipe: RecipeCache, generation: Generation, favourites: set[int]
) -> RecipeOut:
    offers = _plan_offers(generation)
    servings = recipe.servings or 1

    ingredients: list[IngredientOut] = []
    # offer id -> (offer, packs this recipe uses; None when the unit is unknown)
    used: dict[int, tuple[Offer, float | None]] = {}
    allergens: set[str] = set()
    kcal = protein = carbs = fat = 0.0

    for line in recipe.ingredients:
        offer = offers.get(line.canonical_ingredient_id)
        ingredients.append(
            IngredientOut(
                name=line.name,
                amount=_format_amount(line.amount, line.unit),
                offer=offer_out(offer) if offer else None,
                pantry=offer is None,
            )
        )

        if offer is not None:
            packs = _packs(line.amount, line.unit, offer)
            _, so_far = used.get(offer.id, (offer, 0.0))
            used[offer.id] = (offer, None if packs is None or so_far is None else so_far + packs)

        canonical = line.canonical_ingredient
        if canonical is None:
            continue
        allergens.update(canonical.allergens or [])
        grams = _base(line.amount, line.unit)
        if grams is not None:
            share = grams[1] / 100  # nutrition is published per 100 g/ml
            kcal += (canonical.kcal_per_100 or 0) * share
            protein += (canonical.protein_per_100 or 0) * share
            carbs += (canonical.carbs_per_100 or 0) * share
            fat += (canonical.fat_per_100 or 0) * share

    total = leftover = 0.0
    for offer, packs in used.values():
        if packs is None:
            # Unknown unit: charge the whole pack rather than guess a fraction.
            total += offer.price
        elif offer.quantity_basis == "price_basis":
            # Sold loose: you pay for exactly what you take.
            total += offer.price * packs
        else:
            total += offer.price * packs
            leftover += offer.price * (math.ceil(packs) - packs)

    if recipe.total_kcal:
        kcal = recipe.total_kcal

    minutes = recipe.total_time or (recipe.cooking_time or 0) + (recipe.waiting_time or 0)
    steps = [s.strip() for s in (recipe.instructions or "").splitlines() if s.strip()]

    return RecipeOut(
        id=str(recipe.id),
        title=recipe.name,
        summary="",
        servings=servings,
        minutes=minutes,
        diet_type=generation.diet_type if generation.diet_type in COMMON_DIETS else "normal",
        allergens=sorted(allergens),
        ingredients=ingredients,
        steps=steps,
        cost=RecipeCost(
            total_cents=_cents(total),
            per_serving_cents=_cents(total / servings),
            leftover_cents=_cents(leftover),
        ),
        nutrition=Nutrition(
            kcal=round(kcal / servings),
            protein_g=round(protein / servings, 1),
            carbs_g=round(carbs / servings, 1),
            fat_g=round(fat / servings, 1),
        ),
        rationale="",
        is_favourite=recipe.id in favourites,
        in_meal_plan=recipe in generation.planned_recipes,
    )


# --- shopping -----------------------------------------------------------------

def shopping_list(generation: Generation) -> list[ShoppingListItem]:
    """One line per offer the meal plan needs, with the recipes that need it.

    Pack counts come from the planned recipes' own amounts, so adding a second
    recipe that uses the same offer can raise its quantity.
    """
    planned = generation.planned_recipes
    lines = []
    for item in generation.items:
        offer = item.offer
        if offer is None or offer.canonical_ingredient_id is None:
            # Nothing to buy on offer; these show up as pantry lines on recipes.
            continue
        uses = [
            (recipe, line)
            for recipe in planned
            for line in recipe.ingredients
            if line.canonical_ingredient_id == offer.canonical_ingredient_id
        ]
        if not uses:
            continue

        packs: float | None = 0.0
        for _, line in uses:
            share = _packs(line.amount, line.unit, offer)
            packs = None if share is None or packs is None else packs + share

        lines.append(
            ShoppingListItem(
                id=item.id,
                offer=offer_out(offer),
                quantity=max(math.ceil(packs), 1) if packs else 1,
                used_by=list(dict.fromkeys(recipe.name for recipe, _ in uses)),
                checked=item.checked,
            )
        )
    return lines
