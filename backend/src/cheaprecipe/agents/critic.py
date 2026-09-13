"""Critic agent: reviews a proposed meal plan and returns actionable feedback."""

from cheaprecipe.agents.contracts import Plan, Recipe, Ingredient, Critique

def critique(plan: Plan) -> Critique:
    raise NotImplementedError
