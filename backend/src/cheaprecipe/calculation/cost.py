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


def offer_key(item: Item) -> str:
    """Identifies an offer across calls; fridge items have no offer id."""
    return f"offer:{item.offer_id}" if item.offer_id is not None else f"name:{item.name}"


def needs(recipe: Recipe, offers: list[Item], scale: float = 1.0) -> Needs:
    """Match each ingredient to an offer and total the amounts per offer.

    Two lines of a recipe using the same offer (butter for the sauce and for
    the pan) are summed before any pack is rounded up.
    """
    result = Needs()
    for ingredient in recipe.ingredients:
        item = match_offer(ingredient.name, offers)
        if item is None:
            result.unpriced.append(ingredient.name)
            continue
        if item.price == 0:
            continue  # already at home
        try:
            amount = convert(
                ingredient.quantity.amount * scale, ingredient.quantity.unit, item.quantity.unit
            )
        except UnconvertibleUnit:
            result.unpriced.append(ingredient.name)
            continue
        key = offer_key(item)
        _, so_far = result.amounts.get(key, (item, 0.0))
        result.amounts[key] = (item, so_far + amount)
    return result


@dataclass(frozen=True)
class Costing:
    """A recipe priced on its own."""

    # What the packs it forces you to buy cost.
    total: float
    # What the amounts it actually uses are worth; the rest is leftover.
    used: float
    per_serving: float
    unpriced: list[str]


def compute(recipe: Recipe, offers: list[Item]) -> Costing:
    """Price one recipe as if nothing else were being cooked this week."""
    wanted = needs(recipe, offers)
    total = used = 0.0
    for item, amount in wanted.amounts.values():
        quantity = Quantity(amount=amount, unit=item.quantity.unit)
        total += units_needed(quantity, item) * item.price
        used += price_of(quantity, item)
    return Costing(
        total=total,
        used=used,
        per_serving=used / recipe.servings if recipe.servings else used,
        unpriced=wanted.unpriced,
    )


def cost_per_serving(recipe: Recipe, offers: list[Item]) -> float:
    """What one serving's ingredients cost at offer prices.

    Counts what is used, not the whole packs; see `compute` for both. Items no
    offer covers are left out — `compute(...).unpriced` names them.
    """
    return compute(recipe, offers).per_serving
