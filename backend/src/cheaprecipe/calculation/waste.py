"""Leftover / waste calculation: purchased quantity vs. quantity used.

Waste is priced, not just counted. Grams of leftover cannot be traded against
euros of cost without an invented weight, but the money tied up in what gets
thrown away is directly comparable — which is what lets the planner add the
two terms and rank on the sum.
"""

from cheaprecipe.agents.contracts import Item, Recipe


def leftover(bought: float, used: float) -> float:
    """Unused amount, in the offer's own unit. Never negative."""
    return max(bought - used, 0.0)


def leftover_value(bought: float, used: float, item: Item) -> float:
    """The leftover priced in euros, so waste and cost share a currency."""
    raise NotImplementedError


def compute(recipe: Recipe, purchases: list[Item]) -> dict:
    """Standalone waste for one recipe against what was bought for it."""
    raise NotImplementedError
