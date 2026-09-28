"""Orchestrator: runs planner -> critic until the plan passes or the rounds run out.

Each failed round hands the critic's verdict back to the planner agent, which
replaces the recipes it named (planner._feedback_prompt). Every round costs a
planner run and a critic run, so the rounds are capped; when they run out the
last plan is returned with the critique that still stands, rather than nothing.

`fixed` is for topping up a week (POST /generate/refine): recipes the user
already chose. The planner does not see them — they are not candidates — but
the critic reviews them together with the new ones, since variety and cooking
time are properties of the whole week.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from cheaprecipe.agents import critic, planner
from cheaprecipe.agents.contracts import Critique, Item, Plan, Recipe, UserPreference
from cheaprecipe.llm import DEFAULT_MODEL

log = logging.getLogger(__name__)

MAX_ROUNDS = 3


@dataclass(frozen=True)
class LoopResult:
    plan: Plan
    # The verdict on `plan` — passed, or the issues left when rounds ran out.
    critique: Critique
    rounds: int


def run(
    candidate_recipes: list[Recipe],
    offers: list[Item],
    number_of_meals: int,
    user_pref: UserPreference | None = None,
    max_rounds: int = MAX_ROUNDS,
    model_name: str = DEFAULT_MODEL,
    fixed: list[Recipe] = (),
) -> LoopResult:
    """Plan, critique, revise — up to `max_rounds` plans of the new recipes."""
    if max_rounds < 1:
        raise ValueError(f"max_rounds must be at least 1, got {max_rounds}")
    user_pref = user_pref or UserPreference()
    fixed = list(fixed)
    fixed_names = frozenset(r.name for r in fixed)

    plan: Plan | None = None
    verdict: Critique | None = None
    for round_number in range(1, max_rounds + 1):
        plan = planner.plan_with_agent(
            candidate_recipes,
            offers,
            number_of_meals,
            notes=user_pref.notes,
            model_name=model_name,
            previous=plan,
            feedback=verdict,
        )
        week = plan.model_copy(update={"recipes": [*fixed, *plan.recipes]})
        verdict = critic.critique(week, user_pref, model_name=model_name, fixed=fixed_names)
        log.info(
            "round %d: %s%s",
            round_number,
            "passed" if verdict.passed else "rejected",
            f", exchange {verdict.exchange}" if verdict.exchange else "",
        )
        if verdict.passed:
            break

    return LoopResult(plan=plan, critique=verdict, rounds=round_number)
