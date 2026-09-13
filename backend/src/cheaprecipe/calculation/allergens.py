"""Allergen filter — deterministic, never delegated to the LLM."""

from cheaprecipe.agents.contracts import Recipe, Ingredient

def filter_recipes(
    recipes: list[Recipe],
    excluded_allergens: set[str]
    ) -> list[Recipe]:
    """Filter out recipes that have allergens"""
    
    accepted_list = []
    for recipe in recipes:
        for ingredient in recipe.ingredients:
            if ingredient.name in excluded_allergens:
                continue
        accepted_list.append(recipe)
    return accepted_list
