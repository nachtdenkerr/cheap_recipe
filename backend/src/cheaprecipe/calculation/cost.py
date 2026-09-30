"""Recipe cost from offer prices.

`convert` is the only place units are restated, and `price_of` the only place
an amount is priced, so unit handling has exactly one implementation.
`compute` prices a recipe standalone; the planner's Basket prices the
*additional* purchases a recipe forces on top of what a plan already bought,
and both go through `needs` and `units_needed` here.

Items priced at 0 are what the user already has (fridge items, see
app/routers/generate.py). They cover whatever a recipe asks of them, in any
unit, so they never count as a cost nor as unpriced.
"""

import math
from dataclasses import dataclass, field

from cheaprecipe.agents.contracts import Item, Quantity, Recipe
from cheaprecipe.calculation import pantry, regular_prices, weights
from cheaprecipe.matching.offers import match_offer
from cheaprecipe.vocabulary import Unit


class UnconvertibleUnit(ValueError):
    """Two units that no constant converts between (mass vs volume, Stück)."""


# Each family converts by a constant, to its first unit.
_FAMILIES: tuple[dict[str, float], ...] = (
    {"g": 1.0, "kg": 1000.0},
    {"l": 1.0},
    {"Stück": 1.0},
)

# Float division makes 0.3 / 0.1 come out as 3.0000000000000004, which must
# not round up to a fourth pack.
_EPSILON = 1e-9


# Units as stored or scraped -> (Unit, factor). The one place a free-text unit
# becomes one of ours; the database, the API and the dry run all go through it.
_UNIT_NAMES = {
    "g": ("g", 1.0),
    "kg": ("kg", 1.0),
    "l": ("l", 1.0),
    "ml": ("l", 0.001),
    "stück": ("Stück", 1.0),
    "stk": ("Stück", 1.0),
    "piece": ("Stück", 1.0),
    "pieces": ("Stück", 1.0),
}


def unit_of(unit: object) -> tuple[Unit, float] | None:
    """One of our units and the factor to it, for a unit as written; None if unknown.

    Anything that is not a string — None, or pandas' NaN for an empty cell —
    is unknown.
    """
    if not isinstance(unit, str):
        return None
    return _UNIT_NAMES.get(unit.strip().lower())


def quantity_of(amount: float | None, unit: str | None) -> Quantity | None:
    """An amount with a free-text unit ("ml", "Stück") as a Quantity; None if unknown."""
    known = unit_of(unit)
    if amount is None or known is None:
        return None
    return Quantity(amount=amount * known[1], unit=known[0])


def convert(amount: float, from_unit: Unit, to_unit: Unit) -> float:
    """Restate an amount in another unit.

    g <-> kg is a constant. Anything involving Stück, or a volume against a
    mass, is density- or size-dependent and needs per-ingredient data rather
    than a formula — raise instead of guessing, so an unconvertible ingredient
    shows up as a failure rather than a plausible wrong price.
    """
    if from_unit == to_unit:
        return amount
    for family in _FAMILIES:
        if from_unit in family and to_unit in family:
            return amount * family[from_unit] / family[to_unit]
    raise UnconvertibleUnit(f"cannot convert {from_unit} to {to_unit}")


def _to_grams(amount: float, unit: Unit, name: str) -> float | None:
    if unit in ("g", "kg"):
        return convert(amount, unit, "g")
    if unit == "Stück":
        grams = weights.piece_grams(name)
        return amount * grams if grams else None
    grams_per_ml = weights.density(name)  # unit is "l"
    return amount * 1000 * grams_per_ml if grams_per_ml else None


def _from_grams(grams: float, unit: Unit, name: str) -> float | None:
    if unit in ("g", "kg"):
        return convert(grams, "g", unit)
    if unit == "Stück":
        per_piece = weights.piece_grams(name)
        return grams / per_piece if per_piece else None
    grams_per_ml = weights.density(name)
    return grams / (1000 * grams_per_ml) if grams_per_ml else None


def convert_ingredient(amount: float, from_unit: Unit, to_unit: Unit, *names: str) -> float:
    """`convert`, falling back on typical weights for what no constant converts.

    "1 onion" -> kg goes through the onion's piece weight; "2 Tbsp butter" ->
    g through butter's density. `names` are tried in order for each step —
    the recipe's own name first, then the offer's. Still raises
    UnconvertibleUnit for anything calculation/weights.py does not know.
    """
    try:
        return convert(amount, from_unit, to_unit)
    except UnconvertibleUnit:
        pass
    grams = next((g for n in names if (g := _to_grams(amount, from_unit, n)) is not None), None)
    if grams is not None:
        for name in names:
            result = _from_grams(grams, to_unit, name)
            if result is not None:
                return result
    raise UnconvertibleUnit(f"cannot convert {from_unit} to {to_unit} for {names}")


def price_of(quantity: Quantity, item: Item) -> float:
    """What `quantity` of `item` costs, at the offer's price per unit.

    Falls back to the pack price pro rata when the price per unit is quoted in
    a unit the quantity does not convert to (a pack counted in Stück but priced
    per kg); raises UnconvertibleUnit when neither works.
    """
    try:
        amount = convert(quantity.amount, quantity.unit, item.price_per_unit_unit)
        return amount * item.price_per_unit
    except UnconvertibleUnit:
        amount = convert(quantity.amount, quantity.unit, item.quantity.unit)
        return amount / item.quantity.amount * item.price


def units_needed(quantity: Quantity, item: Item) -> int:
    """How many packs of `item` cover `quantity`.

    You cannot buy 300 g of a 500 g pack, and the rounding up is precisely
    what creates leftovers — see calculation/waste.py.
    """
    if item.quantity.amount <= 0:
        raise ValueError(f"{item.name!r} has a pack size of {item.quantity.amount}")
    needed = convert(quantity.amount, quantity.unit, item.quantity.unit)
    if needed <= 0:
        return 0
    return math.ceil(needed / item.quantity.amount - _EPSILON)


@dataclass
class Needs:
    """What a recipe asks of the offers, summed per offer in the offer's unit."""

    # offer key -> (offer, amount needed in offer.quantity.unit)
    amounts: dict[str, tuple[Item, float]] = field(default_factory=dict)
    # Ingredients no offer covers, or whose unit does not convert to the offer's.
    unpriced: list[str] = field(default_factory=list)
    # Ingredients covered by what the user already has (items priced at 0).
    at_home: list[str] = field(default_factory=list)
    # Staples assumed in every kitchen (calculation/pantry.py): free, and not
    # counted when judging how much of a recipe is on offer.
    pantry: list[str] = field(default_factory=list)
    # Not on offer, bought at a typical regular price (calculation/
    # regular_prices.py). In `amounts` like any purchase, but an estimate —
    # and never counted as on offer.
    estimated: list[str] = field(default_factory=list)


def offer_key(item: Item) -> str:
    """Identifies a purchase across calls; fridge and regular-price items have no offer id."""
    if item.offer_id is not None:
        return f"offer:{item.offer_id}"
    return f"regular:{item.name}" if item.estimated else f"name:{item.name}"


def _in_item_unit(ingredient, item: Item, scale: float) -> float | None:
    try:
        return convert_ingredient(
            ingredient.quantity.amount * scale,
            ingredient.quantity.unit,
            item.quantity.unit,
            ingredient.name,
            item.name,
        )
    except UnconvertibleUnit:
        return None


def needs(recipe: Recipe, offers: list[Item], scale: float = 1.0) -> Needs:
    """Resolve each ingredient line and total the amounts per purchase.

    In order: a pantry staple (free); an offer, or a fridge item at 0 EUR; a
    typical regular price (an estimate); and only then unpriced. Two lines of
    a recipe using the same purchase (butter for the sauce and for the pan)
    are summed before any pack is rounded up.
    """
    result = Needs()
    for ingredient in recipe.ingredients:
        if pantry.is_pantry(ingredient.name):
            result.pantry.append(ingredient.name)
            continue
        item = match_offer(ingredient.name, offers)
        if item is not None and item.price == 0:
            result.at_home.append(ingredient.name)
            continue
        amount = _in_item_unit(ingredient, item, scale) if item is not None else None
        if amount is None:
            # No offer, or one whose unit does not convert: buy it regular.
            item = regular_prices.regular_item(ingredient.name)
            amount = _in_item_unit(ingredient, item, scale) if item is not None else None
            if amount is None:
                result.unpriced.append(ingredient.name)
                continue
            result.estimated.append(ingredient.name)
        key = offer_key(item)
        _, so_far = result.amounts.get(key, (item, 0.0))
        result.amounts[key] = (item, so_far + amount)
    return result


@dataclass(frozen=True)
class Costing:
    """A recipe priced on its own."""

    # What the packs it forces you to buy cost, offers and estimates together.
    total: float
    # What the amounts it actually uses are worth; the rest is leftover.
    used: float
    per_serving: float
    unpriced: list[str]
    # The share of `used` that comes from regular-price estimates, and the
    # lines they are for: when not empty, the cost is an estimate ("≈").
    estimated_used: float = 0.0
    estimated: list[str] = field(default_factory=list)


def compute(recipe: Recipe, offers: list[Item]) -> Costing:
    """Price one recipe as if nothing else were being cooked this week."""
    wanted = needs(recipe, offers)
    total = used = estimated_used = 0.0
    for item, amount in wanted.amounts.values():
        quantity = Quantity(amount=amount, unit=item.quantity.unit)
        total += units_needed(quantity, item) * item.price
        value = price_of(quantity, item)
        used += value
        if item.estimated:
            estimated_used += value
    return Costing(
        total=total,
        used=used,
        per_serving=used / recipe.servings if recipe.servings else used,
        unpriced=wanted.unpriced,
        estimated_used=estimated_used,
        estimated=wanted.estimated,
    )


def offer_lines(recipe: Recipe, offers: list[Item]) -> int:
    """How many of a recipe's ingredient lines an offer or the fridge covers.

    Pantry staples count neither way: they are not shopping.
    """
    wanted = needs(recipe, offers)
    return (
        len(recipe.ingredients) - len(wanted.unpriced) - len(wanted.pantry) - len(wanted.estimated)
    )


def offer_share(recipe: Recipe, offers: list[Item]) -> float:
    """The share of a recipe's shopping — lines that are not pantry staples —
    covered by an offer or the fridge.

    0 means the recipe uses nothing on sale and nothing the user has — there
    is no reason to plan it this week, and its cost of 0 would be a lie.
    """
    wanted = needs(recipe, offers)
    shopping = len(recipe.ingredients) - len(wanted.pantry)
    if shopping <= 0:
        return 0.0
    return 1 - (len(wanted.unpriced) + len(wanted.estimated)) / shopping


def cost_per_serving(recipe: Recipe, offers: list[Item]) -> float:
    """What one serving's ingredients cost at offer prices.

    Counts what is used, not the whole packs; see `compute` for both. Items no
    offer covers are left out — `compute(...).unpriced` names them.
    """
    return compute(recipe, offers).per_serving
