"""Candidate recipe retrieval — Spoonacular findByIngredients."""

from __future__ import annotations

import requests

from cheaprecipe.config import spoonacular_api_key

FIND_BY_INGREDIENTS_URL = "https://api.spoonacular.com/recipes/findByIngredients"

# The endpoint degrades with long ingredient lists, so send a handful.
DEFAULT_MAX_INGREDIENTS = 10
DEFAULT_NUMBER = 10


def find_by_ingredients(
    ingredients: list[str],
    number: int = DEFAULT_NUMBER,
    max_ingredients: int = DEFAULT_MAX_INGREDIENTS,
    api_key: str | None = None,
) -> list[dict]:
    """Retrieve candidate recipes for the given English ingredient names."""
    params = {
        "ingredients": ",".join(ingredients[:max_ingredients]),
        "number": number,
        "apiKey": api_key or spoonacular_api_key(),
    }
    response = requests.get(
        FIND_BY_INGREDIENTS_URL,
        params=params,
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def retrieve_candidates(items: list[dict], limit: int = DEFAULT_NUMBER) -> list[dict]:
    """Candidate recipes for selected offer records (see selection/)."""
    ingredients = [
        item["ingredient_en"] for item in items if item.get("ingredient_en")
    ]
    return find_by_ingredients(ingredients, number=limit)
