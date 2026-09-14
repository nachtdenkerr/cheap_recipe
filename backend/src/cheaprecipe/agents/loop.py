"""Orchestrator: runs planner -> critic until the recipe passes or budget runs out."""

from cheaprecipe.agents.contracts import Plan, Recipe

MAX_ROUNDS = 3


def run(
    plan: Plan,
    candidate_recipes: list[Recipe],
    max_rounds: int = MAX_ROUNDS
    ) -> dict:
    raise NotImplementedError
