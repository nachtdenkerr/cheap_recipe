"""Leftover / waste calculation: purchased quantity vs. quantity used.

Waste is priced, not just counted. Grams of leftover cannot be traded against
euros of cost without an invented weight, but the money tied up in what gets
thrown away is directly comparable — which is what lets the planner add the
two terms and rank on the sum.
"""

from cheaprecipe.agents.contracts import Item, Quantity, Recipe
from cheaprecipe.calculation.cost import needs, units_needed


def leftover(bought: float, used: float) -> float:
    """Unused amount, in the offer's own unit. Never negative."""
    return max(bought - used, 0.0)


def leftover_value(bought: float, used: float, item: Item) -> float:
    """The leftover priced in euros, so waste and cost share a currency.

    `bought` and `used` are in the offer's own unit, so the leftover is valued
    at the pack price pro rata — what the unused part cost you.
    """
    if item.quantity.amount <= 0:
        return 0.0
    return leftover(bought, used) * item.price / item.quantity.amount


def compute(recipe: Recipe, offers: list[Item]) -> dict:
    """Standalone waste for one recipe: what is left of each pack it forces.

    For several recipes cooked together, use the planner's Basket — a second
    recipe can use up what the first leaves, which a per-recipe sum misses.
    """
    wanted = needs(recipe, offers)
    lines = []
    for item, used in wanted.amounts.values():
        unit = item.quantity.unit
        bought = units_needed(Quantity(amount=used, unit=unit), item) * item.quantity.amount
        lines.append(
            {
                "name": item.name,
                "unit": unit,
                "bought": bought,
                "used": used,
                "leftover": leftover(bought, used),
                "leftover_value": leftover_value(bought, used, item),
            }
        )
    return {
        "leftover_value": sum(line["leftover_value"] for line in lines),
        "items": lines,
        "unpriced": wanted.unpriced,
    }
