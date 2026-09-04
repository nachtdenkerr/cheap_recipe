"""Orchestrator: runs planner -> critic until the recipe passes or budget runs out."""

MAX_ROUNDS = 3


def run(items: list[dict], candidates: list[dict], max_rounds: int = MAX_ROUNDS) -> dict:
    raise NotImplementedError
