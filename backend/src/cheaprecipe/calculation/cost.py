"""Recipe cost from offer prices."""

from cheaprecipe.agents.contracts import Recipe, Ingredient, Item


def compute(recipe: Recipe, offers: list[Item]) -> float:
    """Compute a recipe cost per serving based on offer prices."""
    cost_per_serving = 0
    servings = recipe.servings
    for ingredient in recipe.ingredients:
        offer = query_offer(ingredient.name, offers)
        if ingredient.from_offer == True:
            amount_per_serving = ingredient.quantity.amount / servings
            if ingredient.quantity.unit != offer.price_per_unit_unit:
                amount_per_serving_converted = convert(
                    amount_per_serving, quantity_unit, offer_unit)
            ingredient_cost_per_serving = amount_per_serving_converted * \
                offer.price_per_unit
        cost_per_serving += ingredient_cost_per_serving
    # TODO: what about the ones not in offer? where to find the price?
    raise NotImplementedError
