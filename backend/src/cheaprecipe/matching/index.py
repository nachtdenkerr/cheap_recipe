"""Recipe <-> ingredient index."""

import json
import logging

from cheaprecipe.agents.contracts import Ingredient, Quantity, Recipe

log = logging.getLogger(__name__)


def parse_ingredient_json(
    ingredients: list[dict],
    used_ingredients: list[dict]
    ) -> list[Ingredient]:
    ingredient_list = []
    for ingredient in ingredients:
        ingre = Ingredient(
            name=ingredient["name"],
            quantity=Quantity(
                amount=ingredient["measures"]["metric"]["amount"],
                unit=ingredient["measures"]["metric"]["unitShort"]
            ),
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


# def build_index(recipes: list[dict]) -> dict:
def parse_recipe_json(json_path: str) -> list[Recipe]:
    input_file = open (json_path)
    recipe_dict = json.load(input_file)
    recipe_list = []

    if not recipe_dict:
        raise ValueError("No recipe retrived.")

    for index, recipe in enumerate(recipe_dict, start=1):
        ingredient_list = parse_ingredient_json(
            recipe["extendedIngredients"],
            recipe["usedIngredients"]
            )
        if not ingredient_list:
            raise ValueError("No ingredient parsed.")
        try:
            recipe = Recipe(
                name=recipe["title"],
                servings=recipe["servings"],
                cooking_time=recipe["readyInMinutes"],
                cuisine=recipe["cuisines"],
                ingredients=ingredient_list
            )
            recipe_list.append(recipe)
            log.info("Parsed %d/%d recipe", index, len(recipe_dict))
        except ValidationError as e:
            raise(e)
    print(recipe_list[1])
    return recipe_list

#TODO: matching the items from queried recipe to the canonical ingredient names

if __name__ == "__main__":
    parse_recipe_json("/Users/thudinh/Desktop/git_projects/cheap_recipe/backend/data/recipes.json")