"""Candidate recipe retrieval — Spoonacular.

Two endpoints, deliberately kept side by side:

- `find_by_ingredients` asks "what can I cook with these?" and matches *any* of
  the ingredients. It knows nothing about diets, allergens or dish types.
- `complex_search` is the filtered search. It takes the user's diet,
  intolerances and cuisines as server-side filters, and with the right flags
  returns instructions, timings and nutrition in the same response — so it
  needs no follow-up call per recipe.

`complex_search` is the one that can actually honour a user profile: filtering
*offers* by diet does not stop findByIngredients returning a recipe with
chicken in it.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

import requests

from cheaprecipe.config import spoonacular_api_key

log = logging.getLogger(__name__)

FIND_BY_INGREDIENTS_URL = "https://api.spoonacular.com/recipes/findByIngredients"
COMPLEX_SEARCH_URL = "https://api.spoonacular.com/recipes/complexSearch"

DEFAULT_MAX_INGREDIENTS = 120
DEFAULT_RECIPE_NUMBER = 40

# Spoonacular caps a single page at 100.
MAX_RECIPE_NUMBER = 100

TIMEOUT = 30


def _csv(value: str | Iterable[str] | None) -> str | None:
    """Join a list into the comma-separated form the API expects.

    Spoonacular reads a comma-separated list for `cuisine` (as OR),
    `excludeCuisine`, `intolerances` and `diet` (as AND) — so one request
    covers several cuisines and there is no need to query them one at a time.
    If that ever proves wrong for a parameter, this is the only place to change.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    joined = ",".join(str(item).strip() for item in value if str(item).strip())
    return joined or None


def _api_key(api_key: str | None) -> str:
    key = api_key or spoonacular_api_key()
    if not key:
        raise RuntimeError(
            "SPOONACULAR_API_KEY is not set — add it to .env at the repo root."
        )
    return key


def _get(url: str, params: dict) -> dict | list:
    """One GET, with the failure modes named rather than left as a status code."""
    # requests omits None-valued params, but being explicit keeps the logged
    # parameter list honest about what was actually sent.
    params = {k: v for k, v in params.items() if v is not None}

    log.debug(
        "GET %s (%s)",
        url,
        ", ".join(f"{k}={v}" for k, v in params.items() if k != "apiKey"),
    )
    response = requests.get(
        url, params=params, headers={"Content-Type": "application/json"}, timeout=TIMEOUT
    )

    if response.status_code == 402:
        # Spoonacular answers 402 when the daily point quota is spent, which is
        # otherwise indistinguishable from a broken request.
        raise RuntimeError(
            "Spoonacular refused the request (HTTP 402) — the daily quota for "
            "this API key is used up."
        )

    response.raise_for_status()
    return response.json()


def _trim(ingredients: list[str], max_ingredients: int) -> list[str]:
    query = ingredients[:max_ingredients]
    if len(ingredients) > max_ingredients:
        log.info(
            "%d ingredients offered, sending the first %d",
            len(ingredients), max_ingredients,
        )
    return query


def complex_search(
    ingredients: list[str],
    number: int = DEFAULT_RECIPE_NUMBER,
    max_ingredients: int = DEFAULT_MAX_INGREDIENTS,
    diet: str | None = None,
    intolerances: str | Iterable[str] | None = None,
    cuisine: str | Iterable[str] | None = None,
    exclude_cuisine: str | Iterable[str] | None = None,
    exclude_ingredients: str | Iterable[str] | None = None,
    dish_type: str | None = None,
    max_ready_time: int | None = None,
    sort: str = "max-used-ingredients",
    add_nutrition: bool = False,
    offset: int = 0,
    api_key: str | None = None,
) -> list[dict]:
    """Filtered recipe search, honouring a user's diet, allergens and cuisines.

    `cuisine` accepts several values in one request (OR); `intolerances`,
    `exclude_cuisine` and `diet` are AND — pass lists, not repeated calls.

    `add_nutrition` is off by default: it raises the quota cost per returned
    recipe, so turn it on once the candidate list has been pruned rather than
    for a wide search.
    """
    if number > MAX_RECIPE_NUMBER:
        log.warning(
            "number=%d exceeds the %d-recipe page limit; requesting %d",
            number, MAX_RECIPE_NUMBER, MAX_RECIPE_NUMBER,
        )
        number = MAX_RECIPE_NUMBER

    query = _trim(ingredients, max_ingredients)
    log.info("complexSearch on %d ingredients: %s", len(query), ", ".join(query))

    payload = _get(
        COMPLEX_SEARCH_URL,
        {
            "apiKey": _api_key(api_key),
            "includeIngredients": _csv(query),
            "excludeIngredients": _csv(exclude_ingredients),
            "diet": _csv(diet),
            "intolerances": _csv(intolerances),
            "cuisine": _csv(cuisine),
            "excludeCuisine": _csv(exclude_cuisine),
            "type": dish_type,
            "maxReadyTime": max_ready_time,
            "sort": sort,
            "number": number,
            "offset": offset or None,
            # Instructions, timings and the used/missed split in one response,
            # so no informationBulk follow-up per recipe.
            "addRecipeInformation": True,
            "addRecipeNutrition": True if add_nutrition else None,
            "fillIngredients": True,
            "ignorePantry": True,
        },
    )

    # complexSearch wraps its results; findByIngredients returns a bare list.
    recipes = payload.get("results", []) if isinstance(payload, dict) else payload
    total = payload.get("totalResults") if isinstance(payload, dict) else None

    if total is not None:
        log.info("complexSearch: %d recipes of %d matching", len(recipes), total)
    else:
        log.info("complexSearch returned %d recipes", len(recipes))

    if not recipes:
        # Almost always over-filtering rather than a thin database.
        log.warning(
            "no recipes matched — filters were diet=%s intolerances=%s cuisine=%s type=%s",
            diet, _csv(intolerances), _csv(cuisine), dish_type,
        )

    return recipes


def find_by_ingredients(
    ingredients: list[str],
    number: int = DEFAULT_RECIPE_NUMBER,
    max_ingredients: int = DEFAULT_MAX_INGREDIENTS,
    api_key: str | None = None,
) -> list[dict]:
    """Retrieve candidate recipes for the given English ingredient names.

    Matches *any* of the ingredients and applies no dietary filter — see
    `complex_search` when the user has a diet, an allergy or a block list.
    """
    query = _trim(ingredients, max_ingredients)
    log.info("findByIngredients on %d ingredients: %s", len(query), ", ".join(query))

    recipes = _get(
        FIND_BY_INGREDIENTS_URL,
        {"ingredients": _csv(query), "number": number, "apiKey": _api_key(api_key)},
    )

    log.info("findByIngredients returned %d recipes", len(recipes))
    if not recipes:
        log.warning("no recipes matched %s", ", ".join(query))

    return recipes


def retrieve_candidates(items: list[dict], limit: int = DEFAULT_RECIPE_NUMBER) -> list[dict]:
    """Candidate recipes for selected offer records (see selection/)."""
    ingredients = [
        item["ingredient_en"] for item in items if item.get("ingredient_en")
    ]
    skipped = len(items) - len(ingredients)
    if skipped:
        log.warning("%d/%d selected items carry no ingredient_en", skipped, len(items))
    return find_by_ingredients(ingredients, number=limit)
