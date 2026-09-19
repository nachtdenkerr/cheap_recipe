"""The closed vocabularies the offer side and the agent side share.

Defined as `Literal`s and derived into tuples with `typing.get_args`, so there
is one definition per vocabulary that is both statically checkable (pydantic,
mypy, editor completion) and available at runtime for argparse choices and
pandas filtering. A YAML file would give the runtime half and lose the other.

The one exception is `excluded_categories.yml`, and it is an exception for a
reason: those lists are each chain's own department names, they change when a
chain reorganises its aisles rather than when this code changes, and no Literal
would ever be written against them. Nothing is lost by keeping them out of
Python, and an editable file is what lets someone fix a rename without one.

`DietType` and `Cuisine` are Spoonacular's own vocabularies, so a user's
preference passes straight through to complexSearch as a query parameter.

There is deliberately no offer-side diet vocabulary. A grocery item satisfies
many diets at once, so labelling each item with one diet could never be
correct; diet is decided on the recipe instead.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal, get_args

import yaml

# --- the chains we ingest offers from ----------------------------------------

Store = Literal["edeka", "aldi"]
STORES: tuple[str, ...] = get_args(Store)

EXCLUDED_CATEGORIES_FILE = Path(__file__).with_name("excluded_categories.yml")


@lru_cache(maxsize=1)
def _excluded() -> dict:
    """The parsed excluded_categories.yml, read once."""
    with EXCLUDED_CATEGORIES_FILE.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    missing = [store for store in STORES if store not in data]
    if missing:
        # A store with no entry would silently keep its whole non-food range,
        # which looks like a bad LLM rather than a missing config.
        raise KeyError(
            f"{EXCLUDED_CATEGORIES_FILE.name} has no entry for {missing}; "
            f"every store in vocabulary.Store needs one."
        )
    return data


def _store_entry(store: str) -> dict:
    if store not in STORES:
        raise ValueError(f"Unknown store {store!r}; expected one of {list(STORES)}.")
    return _excluded()[store] or {}


def excluded_categories(store: Store) -> tuple[str, ...]:
    """The department names of `store` that never yield a recipe ingredient."""
    return tuple(_store_entry(store).get("categories") or ())


def excluded_description_terms(store: Store) -> tuple[str, ...]:
    """Substrings marking non-food filed inside a food department of `store`."""
    return tuple(_store_entry(store).get("description_terms") or ())


Unit = Literal[
    "g",
    "kg",
    "l",
    "Stück"
]
# --- what a user can ask for (Spoonacular's `diet` values, plus "normal") ----

DietType = Literal[
    "gluten-free",
    "ketogenic",
    "vegan",
    "vegetarian",
    "lacto-vegetarian",
    "ovo-vegetarian",
    "pescetarian",
    "paleo",
    "primal",
    "normal",
]
DIET_TYPES: tuple[str, ...] = get_args(DietType)

# --- Spoonacular's `cuisine` values -----------------------------------------

Cuisine = Literal[
    "African",
    "Asian",
    "American",
    "British",
    "Cajun",
    "Caribbean",
    "Chinese",
    "Eastern European",
    "European",
    "French",
    "German",
    "Greek",
    "Indian",
    "Irish",
    "Italian",
    "Japanese",
    "Jewish",
    "Korean",
    "Latin American",
    "Mediterranean",
    "Mexican",
    "Middle Eastern",
    "Nordic",
    "Southern",
    "Spanish",
    "Thai",
    "Vietnamese",
]
CUISINES: tuple[str, ...] = get_args(Cuisine)

CookingLevel = Literal["easy", "medium", "hard"]
COOKING_LEVELS: tuple[str, ...] = get_args(CookingLevel)

# "normal" is our own value for "no dietary restriction"; Spoonacular has no
# such diet and would reject it, so it maps to "send no diet filter".
NO_DIETARY_RESTRICTION = "normal"


def spoonacular_diet(diet_type: str | None) -> str | None:
    """The value to send as complexSearch's `diet`, or None to omit it."""
    if diet_type is None or diet_type == NO_DIETARY_RESTRICTION:
        return None
    return diet_type
