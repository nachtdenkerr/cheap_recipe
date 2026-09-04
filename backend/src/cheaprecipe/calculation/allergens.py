"""Allergen filter — deterministic, never delegated to the LLM."""


def filter_recipes(recipes: list[dict], excluded_allergens: set[str]) -> list[dict]:
    raise NotImplementedError
