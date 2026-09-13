"""The closed vocabularies the offer side and the agent side share.

Defined as `Literal`s and derived into tuples with `typing.get_args`, so there
is one definition per vocabulary that is both statically checkable (pydantic,
mypy, editor completion) and available at runtime for argparse choices and
pandas filtering. A YAML file would give the runtime half and lose the other.

`DietType` and `Cuisine` are Spoonacular's own vocabularies, so a user's
preference passes straight through to complexSearch as a query parameter.

There is deliberately no offer-side diet vocabulary. A grocery item satisfies
many diets at once, so labelling each item with one diet could never be
correct; diet is decided on the recipe instead.
"""

from typing import Literal, get_args

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
