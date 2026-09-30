"""Which diets a recipe fits — deterministic, never delegated to the LLM.

Two sources, and a recipe gets the stricter answer of the two:

- Spoonacular's own flags (`vegan`, `vegetarian`, `diets`), when the recipe
  came with them;
- the words of its ingredients: any meat means it fits no restricted diet,
  fish or seafood makes it pescetarian at most, dairy, egg or honey
  vegetarian at most (allergens.py supplies the fish, dairy and egg words).

"Stricter" because the two can disagree, and the costly mistake is serving
meat to a vegetarian — a flag that says vegetarian next to "ground beef" loses.

Diets are ranked: a vegan recipe also fits vegetarians, pescetarians and
everyone else (`fits`).
"""

from __future__ import annotations

from collections.abc import Iterable

from cheaprecipe.calculation.allergens import allergens_of
from cheaprecipe.matching.offers import tokens
from cheaprecipe.vocabulary import CommonDiet

# Least to most restrictive: a recipe fits every diet up to its own.
_RANK: dict[str, int] = {"normal": 0, "pescetarian": 1, "vegetarian": 2, "vegan": 3}

MEAT_WORDS = frozenset({
    "meat", "beef", "pork", "chicken", "bacon", "ham", "sausage", "lamb", "mutton", "veal",
    "turkey", "duck", "goose", "pancetta", "prosciutto", "salami", "chorizo", "pepperoni",
    "mince", "steak", "chuck", "sirloin", "tenderloin", "brisket", "meatball", "gelatin",
    "gelatine", "lard", "venison", "rabbit", "liver", "oxtail", "kielbasa", "bratwurst",
    "frankfurter", "guanciale", "speck",
})
# Words that make a meat word not meat.
_NOT_MEAT = frozenset({"vegetarian", "vegan", "veggie", "meatless", "plant"})

_SEAFOOD = {"fish", "crustaceans", "molluscs"}
_ANIMAL = {"milk", "eggs"}


def ingredient_diet(name: str) -> CommonDiet:
    """The most restrictive diet one ingredient fits."""
    words = tokens(name)
    if words & MEAT_WORDS and not words & _NOT_MEAT:
        return "normal"
    found = allergens_of(name)
    if found & _SEAFOOD:
        return "pescetarian"
    if found & _ANIMAL or "honey" in words:
        return "vegetarian"
    return "vegan"


def spoonacular_diet(recipe: dict) -> CommonDiet | None:
    """What Spoonacular's flags say, or None when the recipe carries none."""
    if not any(key in recipe for key in ("vegan", "vegetarian", "diets")):
        return None
    if recipe.get("vegan"):
        return "vegan"
    if recipe.get("vegetarian"):
        return "vegetarian"
    if "pescatarian" in {d.lower() for d in recipe.get("diets") or ()}:
        return "pescetarian"
    return "normal"


def recipe_diet(ingredients: Iterable[str], recipe: dict | None = None) -> CommonDiet:
    """The most restrictive diet the whole recipe fits — the stricter of both sources."""
    diets = [ingredient_diet(name) for name in ingredients]
    if recipe is not None and (flagged := spoonacular_diet(recipe)) is not None:
        diets.append(flagged)
    return min(diets, key=_RANK.__getitem__, default="vegan")


def fits(recipe_diet: str | None, wanted: str | None) -> bool:
    """Whether a recipe of `recipe_diet` may be planned for someone on `wanted`.

    An unknown recipe diet counts as "normal": it is only planned for someone
    with no restriction.
    """
    return _RANK.get(recipe_diet or "normal", 0) >= _RANK.get(wanted or "normal", 0)
