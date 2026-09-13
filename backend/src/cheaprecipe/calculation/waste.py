"""Leftover / waste calculation: purchased quantity vs. quantity used."""

from cheaprecipe.agents.contracts import Recipe, Ingredient, Item


def compute(recipe: Recipe, purchases: list[Item]) -> dict:
    raise NotImplementedError
