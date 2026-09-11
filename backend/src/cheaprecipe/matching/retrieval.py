"""Candidate recipe retrieval — Spoonacular findByIngredients."""

from __future__ import annotations

import logging

import requests

from cheaprecipe.config import spoonacular_api_key

log = logging.getLogger(__name__)

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
    key = api_key or spoonacular_api_key()
    if not key:
        raise RuntimeError(
            "SPOONACULAR_API_KEY is not set — add it to .env at the repo root."
        )

    query = ingredients[:max_ingredients]
    if len(ingredients) > max_ingredients:
        log.info(
            "%d ingredients offered, sending the first %d (endpoint degrades beyond that)",
            len(ingredients), max_ingredients,
        )
    log.info("querying spoonacular on: %s", ", ".join(query))

    params = {
        "ingredients": ",".join(query),
        "number": number,
        "apiKey": key,
    }
    response = requests.get(
        FIND_BY_INGREDIENTS_URL,
        params=params,
        headers={"Content-Type": "application/json"},
        timeout=30,
    )

    if response.status_code == 402:
        # Spoonacular answers 402 when the daily point quota is spent, which is
        # otherwise indistinguishable from a broken request.
        raise RuntimeError(
            "Spoonacular refused the request (HTTP 402) — the daily quota for "
            "this API key is used up."
        )

    response.raise_for_status()

    recipes = response.json()
    log.info("spoonacular returned %d recipes", len(recipes))
    if not recipes:
        log.warning("no recipes matched %s", ", ".join(query))

    return recipes


def retrieve_candidates(items: list[dict], limit: int = DEFAULT_NUMBER) -> list[dict]:
    """Candidate recipes for selected offer records (see selection/)."""
    ingredients = [
        item["ingredient_en"] for item in items if item.get("ingredient_en")
    ]
    skipped = len(items) - len(ingredients)
    if skipped:
        log.warning("%d/%d selected items carry no ingredient_en", skipped, len(items))
    return find_by_ingredients(ingredients, number=limit)
