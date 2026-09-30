"""ORM rows -> the response shapes in app/schemas.

The frontend's `Recipe` is richer than what the database stores, so part of it
is derived here from the plan (`Generation`) the recipe belongs to:

- an ingredient is on offer when an offer in the same plan resolves to the same
  canonical ingredient; otherwise it is a pantry staple (calculation/pantry.py,
  free), bought at a typical regular price (calculation/regular_prices.py, an
  estimate), or — when neither table knows it — unpriced;
- cost is the used share of each pack, offers exact and regular prices
  estimated (`estimated_cents`); unpriced lines are counted (`unpriced_count`)
  so the frontend shows the cost as "≈" or as a floor ("from ...");
- nutrition and allergens come from the canonical ingredients.

The shopping list covers only the recipes the user added to their meal plan,
not everything the planner suggested: every ingredient they need except
pantry staples — offers, and the rest at their estimated regular price.

Not stored anywhere yet, so returned empty: `summary` and `rationale`.
Regular prices are estimates, not the store's shelf prices, so the API makes
no claim about savings.
"""

import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.schemas.auth import User as UserOut
from app.schemas.markets import Market as MarketOut
from app.schemas.recipes import Nutrition, RecipeCost
from app.schemas.recipes import Offer as OfferOut
from app.schemas.recipes import Recipe as RecipeOut
from app.schemas.recipes import RecipeIngredient as IngredientOut
from app.schemas.shopping import ShoppingListItem
from cheaprecipe.agents.contracts import Item, Quantity
from cheaprecipe.calculation import cost
from cheaprecipe.calculation.allergens import allergens_of
from cheaprecipe.calculation.pantry import is_pantry
from cheaprecipe.calculation.regular_prices import REGULAR_PRICES, regular_item
from cheaprecipe.calculation.weights import best_key
from cheaprecipe.db.load import chain_of
from cheaprecipe.db.models import (
    Generation,
    GenerationItem,
    Offer,
    RecipeCache,
    RecipeIngredient,
    User,
)
from cheaprecipe.matching.offers import canonical
from cheaprecipe.vocabulary import ALLERGENS, COMMON_DIETS, CUISINES, DEFAULT_MEAL_TYPES

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
    """A recipe line's amount as a recipe would print it: "113 g", "30 ml", "3"."""
    if amount is None:
        return unit or "to taste"
    if unit in ("g", "kg", "l", "ml", "Stück"):
        return _readable(amount, unit, pieces="")
    return f"{amount:g} {unit}".strip() if unit else f"{amount:g}"


def _number(value: float, places: int) -> str:
    return f"{value:.{places}f}".rstrip("0").rstrip(".") if places else f"{value:.0f}"


def _readable(amount: float, unit: str, pieces: str = "pcs") -> str:
    """An amount as people say it: "7 g" not "0.00675 kg", "30 ml" not "0.03 l".

    Grams and millilitres are whole numbers from 10 up (a recipe's "113.398 g"
    is Spoonacular converting 4 oz); pieces keep one decimal ("1.5 pcs").
    """
    if unit == "kg" and amount < 1:
        amount, unit = amount * 1000, "g"
    elif unit == "l" and amount < 1:
        amount, unit = amount * 1000, "ml"
    if unit in ("g", "ml"):
        return f"{_number(amount, 0 if amount >= 10 else 1)} {unit}"
    if unit == "Stück":
        count = _number(amount, 1)
        return f"{count} {pieces}".strip()
    return f"{_number(amount, 2)} {unit}"


def shopping_name(ingredient: str) -> str:
    """What a non-offer ingredient is bought as: its regular-price entry
    ("carrots" -> "carrot"), else its canonical name. Lines with the same
    shopping name are one line on the shopping list."""
    return best_key(REGULAR_PRICES, ingredient) or canonical(ingredient)


def _estimate(line: RecipeIngredient) -> tuple[Item, float] | None:
    """The regular-price item for a line and the amount of it, in its unit."""
    item = regular_item(line.name)
    quantity = cost.quantity_of(line.amount, line.unit)
    if item is None or quantity is None:
        return None
    try:
        amount = cost.convert_ingredient(
            quantity.amount, quantity.unit, item.quantity.unit, line.name, item.name
        )
    except cost.UnconvertibleUnit:
        return None
    return item, amount


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
        home_markets=[market_out(m) for m in (pref.home_markets if pref else [])],
        cuisines=[c for c in ((pref.cuisines if pref else None) or []) if c in CUISINES],
        white_list=list((pref.white_list if pref else None) or []),
        black_list=list((pref.black_list if pref else None) or []),
        health_goal=pref.health_goal if pref else None,
        age=pref.age if pref else None,
        gender=pref.gender if pref else None,
        week_time_availability=pref.week_time_availability if pref else None,
        meal_types=list((pref.meal_types if pref else None) or DEFAULT_MEAL_TYPES),
    )


# --- recipes ------------------------------------------------------------------

def market_out(branch) -> MarketOut:
    return MarketOut(
        id=branch.id,
        chain=chain_of(branch),
        market_id=branch.market_id,
        name=branch.name or (branch.supermarket.name if branch.supermarket else branch.market_id),
        street=branch.street,
        postal_code=branch.postal_code,
        city=branch.city,
    )


def offer_out(offer: Offer) -> OfferOut:
    return OfferOut(
        id=offer.id,
        title=offer.title,
        ingredient_en=offer.ingredient_en,
        category=offer.category,
        market=offer.address.name if offer.address else None,
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
    # Not on offer: priced at a typical regular price, or not priced at all.
    estimated = 0.0
    unpriced = 0

    for line in recipe.ingredients:
        offer = offers.get(line.canonical_ingredient_id)
        at_home = offer is None and is_pantry(line.name)
        regular_pack = None
        if offer is None and not at_home:
            found = _estimate(line)
            if found is None:
                unpriced += 1
            else:
                item, amount = found
                estimated += cost.price_of(Quantity(amount=amount, unit=item.quantity.unit), item)
                regular_pack = item.price
        ingredients.append(
            IngredientOut(
                name=line.name,
                amount=_format_amount(line.amount, line.unit),
                offer=offer_out(offer) if offer else None,
                pantry=at_home,
                regular_price_cents=_cents(regular_pack) if regular_pack is not None else None,
            )
        )

        if offer is not None:
            packs = _packs(line.amount, line.unit, offer)
            _, so_far = used.get(offer.id, (offer, 0.0))
            used[offer.id] = (offer, None if packs is None or so_far is None else so_far + packs)

        allergens.update(allergens_of(line.name))
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
    total += estimated

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
        # The recipe's own diet, never the user's: a badge must not claim a
        # beef soup is vegetarian because the user is.
        diet_type=recipe.diet_type if recipe.diet_type in COMMON_DIETS else "normal",
        allergens=sorted(allergens),
        ingredients=ingredients,
        steps=steps,
        cost=RecipeCost(
            total_cents=_cents(total),
            per_serving_cents=_cents(total / servings),
            leftover_cents=_cents(leftover),
            estimated_cents=_cents(estimated),
            unpriced_count=unpriced,
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
        course="breakfast" if recipe.course == "breakfast" else "main",
    )


# --- shopping -----------------------------------------------------------------

def shopping_list(generation: Generation) -> list[ShoppingListItem]:
    """Everything the meal plan needs except pantry staples, with the recipes
    that need it.

    Offer lines first: pack counts come from the planned recipes' own amounts,
    so adding a second recipe that uses the same offer can raise its quantity.
    Then the rest, one line per shopping name, at an estimated regular price
    where calculation/regular_prices.py knows one.
    """
    planned = generation.planned_recipes
    offers = _plan_offers(generation)
    lines = []
    for item in generation.items:
        offer = item.offer
        if offer is not None and offer.canonical_ingredient_id is not None:
            line = _offer_line(item, offer, planned)
        elif offer is None and item.name:
            line = _regular_line(item, planned, offers)
        else:
            line = None
        if line is not None:
            lines.append(line)
    return lines


def _offer_line(item: GenerationItem, offer: Offer, planned) -> ShoppingListItem | None:
    uses = [
        (recipe, line)
        for recipe in planned
        for line in recipe.ingredients
        if line.canonical_ingredient_id == offer.canonical_ingredient_id
    ]
    if not uses:
        return None

    packs: float | None = 0.0
    for _, line in uses:
        share = _packs(line.amount, line.unit, offer)
        packs = None if share is None or packs is None else packs + share

    return ShoppingListItem(
        id=item.id,
        name=offer.ingredient_en or offer.title,
        offer=offer_out(offer),
        quantity=max(math.ceil(packs), 1) if packs else 1,
        used_by=list(dict.fromkeys(recipe.name for recipe, _ in uses)),
        checked=item.checked,
    )


def _regular_line(
    item: GenerationItem, planned, offers: dict[int, Offer]
) -> ShoppingListItem | None:
    """A non-offer line: what the planned recipes need of `item.name`."""
    uses = [
        (recipe, line)
        for recipe in planned
        for line in recipe.ingredients
        if line.canonical_ingredient_id not in offers
        and not is_pantry(line.name)
        and shopping_name(line.name) == item.name
    ]
    if not uses:
        return None

    regular = regular_item(item.name)
    needed: float | None = 0.0
    for _, line in uses:
        found = _estimate(line)
        needed = None if found is None or needed is None else needed + found[1]

    if regular is not None and needed is not None:
        packs = cost.units_needed(Quantity(amount=needed, unit=regular.quantity.unit), regular)
        quantity = max(packs, 1)
        amount = _readable(needed, regular.quantity.unit)
        estimated = _cents(quantity * regular.price)
    else:
        # No regular price, or amounts that do not add up: list it, unpriced.
        quantity = 1
        amount = ", ".join(_format_amount(line.amount, line.unit) for _, line in uses)
        estimated = None

    return ShoppingListItem(
        id=item.id,
        name=item.name,
        offer=None,
        amount=amount,
        quantity=quantity,
        estimated_price_cents=estimated,
        used_by=list(dict.fromkeys(recipe.name for recipe, _ in uses)),
        checked=item.checked,
    )
