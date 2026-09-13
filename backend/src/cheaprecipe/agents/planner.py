"""
Planner agent: plan weekly meals based on found recipe from Spoonacular.
Use greedy algorithm to select the cheapest, most low waste and lowest
cooking time recipes.
"""

from cheaprecipe.agents.contracts import Plan, Recipe, Ingredient

def plan(recipes: list[Recipe], number_of_meals: int) -> Plan:
    """Compute cost, waste from each recipe and propose a meal plan."""
    raise NotImplementedError
