"""Recipe <-> ingredient index."""

import json
import logging

from cheaprecipe.agents.contracts import Ingredient, Quantity, Recipe
from cheaprecipe.vocabulary import CUISINES

log = logging.getLogger(__name__)

# Spoonacular's metric `unitShort` -> (our Unit, factor). Spoons become litres:
# a volume is honest for a spoonful, and anything bought by weight then shows
# up as unpriced rather than as a guessed density. An empty unit is a count
# ("2 eggs"), as are the size words Spoonacular puts in the unit field.
_METRIC_UNITS = {
    "g": ("g", 1.0),
    "kg": ("kg", 1.0),
    "ml": ("l", 0.001),
    "l": ("l", 1.0),
    "tbsp": ("l", 0.015),
    "tbsps": ("l", 0.015),
    "tsp": ("l", 0.005),
    "tsps": ("l", 0.005),
    **{
        word: ("Stück", 1.0)
        for word in (
            "", "large", "medium", "small", "medium size", "clove", "cloves",
            "slice", "slices", "sheet", "sheets", "stalk", "stalks", "cube",
            "cubes", "bunch", "piece", "pieces",
        )
    },
}


def metric_quantity(ingredient: dict) -> Quantity | None:
    """The ingredient's metric amount in our units; None for "1 serving", "a pinch"."""
    metric = ingredient["measures"]["metric"]
    known = _METRIC_UNITS.get(metric["unitShort"].strip().lower())
    if known is None:
        return None
    unit, factor = known
    return Quantity(amount=metric["amount"] * factor, unit=unit)


def parse_ingredient_json(
    ingredients: list[dict],
    used_ingredients: list[dict]
    ) -> list[Ingredient]:
    ingredient_list = []
    for ingredient in ingredients:
        quantity = metric_quantity(ingredient)
        if quantity is None:
            log.debug(
                "skipping %r: no amount in %r",
                ingredient["name"], ingredient["measures"]["metric"]["unitShort"],
            )
            continue
        ingre = Ingredient(
            name=ingredient["name"],
            quantity=quantity,
            ingredient_type=ingredient["aisle"]
        )
        from_offer(ingre, used_ingredients)
        ingredient_list.append(ingre)
    return ingredient_list


def from_offer(ingredient_model: Ingredient, used_ingredients: dict) -> None:
    for ingredient in used_ingredients:
        if ingredient_model.name == ingredient["name"]:
            ingredient_model.from_offer = True
            return
        else:
            ingredient_model.from_offer = False


# Spoonacular dishTypes that are a meal on their own. A recipe with none of
# these — a dessert, a dressing, a side, a snack — is not planned as a meal.
MEAL_DISH_TYPES = frozenset(
    {"main course", "main dish", "lunch", "dinner", "breakfast", "brunch", "soup"}
)


def is_meal(recipe: dict) -> bool:
    """Whether Spoonacular calls this a meal. No dishTypes at all means unknown: kept."""
    dish_types = {d.lower() for d in recipe.get("dishTypes") or ()}
    return not dish_types or bool(dish_types & MEAL_DISH_TYPES)


def recipe_times(recipe: dict) -> tuple[int | None, int]:
    """(preparation, cooking) minutes.

    Spoonacular's own split when it has both parts; otherwise readyInMinutes
    as the cooking time. Beware: readyInMinutes is 45 whenever Spoonacular
    does not know the time, and on real data it usually does not.
    """
    prep = recipe.get("preparationMinutes")
    cook = recipe.get("cookingMinutes")
    if prep is not None and cook is not None and prep >= 0 and cook > 0:
        return prep, cook
    return None, recipe["readyInMinutes"]


# def build_index(recipes: list[dict]) -> dict:
def parse_recipe_json(json_path: str, meals_only: bool = True) -> list[Recipe]:
    with open(json_path) as input_file:
        recipe_dict = json.load(input_file)
        recipe_list = []

        if not recipe_dict:
            raise ValueError("No recipe retrived.")

        for index, recipe in enumerate(recipe_dict, start=1):
            if meals_only and not is_meal(recipe):
                log.info(
                    "Skipping %r: not a meal (%s)",
                    recipe["title"], ", ".join(recipe.get("dishTypes") or ()),
                )
                continue
            ingredient_list = parse_ingredient_json(
                recipe["extendedIngredients"],
                recipe["usedIngredients"]
                )
            if not ingredient_list:
                # e.g. every line "1 serving": nothing to price, so nothing to
                # plan with — skip it rather than lose the whole batch.
                log.warning("Skipping %r: no ingredient with an amount", recipe["title"])
                continue
            preparation, cooking = recipe_times(recipe)
            recipe = Recipe(
                name=recipe["title"],
                servings=recipe["servings"],
                preparation_time=preparation,
                cooking_time=cooking,
                # Spoonacular knows cuisines our vocabulary does not.
                cuisine=[c for c in recipe["cuisines"] if c in CUISINES],
                ingredients=ingredient_list,
                source="spoonacular",
                external_id=str(recipe["id"]),
            )
            recipe_list.append(recipe)
            log.info("Parsed %d/%d recipe", index, len(recipe_dict))
        return recipe_list

#TODO: matching the items from queried recipe to the canonical ingredient names

if __name__ == "__main__":
    from cheaprecipe.config import DATA_DIR

    parse_recipe_json(str(DATA_DIR / "edeka_recipes.json"))