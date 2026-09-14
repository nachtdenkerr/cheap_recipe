"""Recipe cost from offer prices.

`price_of` is the primitive: everything that needs to know what an amount of
an ingredient costs goes through it, so unit conversion has exactly one
implementation. `compute` prices a recipe standalone; the planner prices the
*additional* purchases a recipe forces, and both are built on the same call.
"""

from cheaprecipe.agents.contracts import Item, Quantity, Recipe
from cheaprecipe.vocabulary import Unit


def convert(amount: float, from_unit: Unit, to_unit: Unit) -> float:
    """Restate an amount in another unit.

    g <-> kg is a constant. Anything involving Stück, or a volume against a
    mass, is density- or size-dependent and needs per-ingredient data rather
    than a formula — raise instead of guessing, so an unconvertible ingredient
    shows up as a failure rather than a plausible wrong price.
    """
    raise NotImplementedError


def price_of(quantity: Quantity, item: Item) -> float:
    """What `quantity` of `item` costs, at the offer's price per unit."""
    raise NotImplementedError


def units_needed(quantity: Quantity, item: Item) -> int:
    """How many packs of `item` cover `quantity`.

    You cannot buy 300 g of a 500 g pack, and the rounding up is precisely
    what creates leftovers — see calculation/waste.py.
    """
    raise NotImplementedError


def cost_per_serving(recipe: Recipe, offers: list[Item]) -> float:
    """Compute a recipe cost per serving based on offer prices."""
    cost_per_serving = 0
    servings = recipe.servings
    for ingredient in recipe.ingredients:
        offer = query_offer(ingredient.name, offers)
        if ingredient.from_offer == True:
            amount_per_serving = ingredient.quantity.amount / servings
            if ingredient.quantity.unit != offer.price_per_unit_unit:
                amount_per_serving_converted = convert(
                    amount_per_serving, quantity_unit, offer_unit)
            ingredient_cost_per_serving = amount_per_serving_converted * \
                offer.price_per_unit
        cost_per_serving += ingredient_cost_per_serving
    # TODO: what about the ones not in offer? where to find the price?
    raise NotImplementedError
