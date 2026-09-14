"""Critic agent: reviews a proposed meal plan and returns actionable feedback."""

from cheaprecipe.agents.contracts import Critique, Plan


def critique(plan: Plan) -> Critique:
    raise NotImplementedError
