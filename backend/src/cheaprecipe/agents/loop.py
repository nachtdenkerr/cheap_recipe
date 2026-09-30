"""Orchestrator: runs planner -> critic until the plan passes or the rounds run out.

Each failed round hands the critic's verdict back to the planner agent, which
replaces the recipes it named (planner._feedback_prompt). The feedback adds
up: the agent sees every issue raised so far and may not bring back a recipe
the critic rejected in any round — or it fixes one problem by re-creating an
earlier one. Every round costs a
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

from pydantic_ai.exceptions import AgentRunError

from cheaprecipe.agents import critic, planner
from cheaprecipe.agents.contracts import Critique, Item, Plan, Recipe, UserPreference
from cheaprecipe.llm import DEFAULT_MODEL
from cheaprecipe.observability.decorators import traced

log = logging.getLogger(__name__)

MAX_ROUNDS = 3


@dataclass(frozen=True)
class LoopResult:
    plan: Plan
    # The verdict on `plan` — passed, or the issues left when rounds ran out.
    critique: Critique
    rounds: int


@traced("planner-critic loop")
def run(
    candidate_recipes: list[Recipe],
    offers: list[Item],
    number_of_meals: int,
    user_pref: UserPreference | None = None,
    max_rounds: int = MAX_ROUNDS,
    model_name: str = DEFAULT_MODEL,
    fixed: list[Recipe] = (),
    courses: dict[str, int] | None = None,
) -> LoopResult:
    """Plan, critique, revise — up to `max_rounds` plans of the new recipes.

    `courses`: how many breakfast and main recipes (planner.course_quotas).
    """
    if max_rounds < 1:
        raise ValueError(f"max_rounds must be at least 1, got {max_rounds}")
    user_pref = user_pref or UserPreference()
    fixed = list(fixed)
    fixed_names = frozenset(r.name for r in fixed)

    def review(plan: Plan, round_number: int) -> Critique:
        week = plan.model_copy(update={"recipes": [*fixed, *plan.recipes]})
        verdict = critic.critique(week, user_pref, model_name=model_name, fixed=fixed_names)
        log.info(
            "round %d/%d: planned %s — critic %s%s",
            round_number, max_rounds, [r.name for r in plan.recipes],
            "passed" if verdict.passed else "rejected",
            f", exchange {verdict.exchange}" if verdict.exchange else "",
        )
        if verdict.assessment:
            log.info("round %d assessment: %s", round_number, verdict.assessment)
        for issue in verdict.issues:
            log.info("round %d issue: %s", round_number, issue)
        for suggestion in verdict.suggestions:
            log.info("round %d suggestion: %s", round_number, suggestion)
        return verdict

    offered = planner.using_offers(candidate_recipes, offers)
    if len(offered) <= number_of_meals:
        # Nothing to choose: every candidate is in the week (as far as the
        # courses and variety allow). The planner agent would spend its
        # requests to return what the greedy week already is — the critic
        # still reviews it, but there is nothing to revise it with.
        plan = planner.plan(offered, offers, number_of_meals, varied=True, courses=courses)
        log.info("%d candidates for %d meals: no choice to make, planner agent skipped",
                 len(offered), number_of_meals)
        if not plan.recipes:
            return LoopResult(plan=plan, critique=Critique(
                passed=False, issues=["No candidate recipe could be planned."]), rounds=0)
        return LoopResult(plan=plan, critique=review(plan, 1), rounds=1)

    plan: Plan | None = None
    verdict: Critique | None = None
    feedback: Critique | None = None  # everything the critic said so far
    for round_number in range(1, max_rounds + 1):
        try:
            revised = planner.plan_with_agent(
                candidate_recipes,
                offers,
                number_of_meals,
                notes=user_pref.notes,
                model_name=model_name,
                previous=plan,
                feedback=feedback,
                courses=courses,
            )
        except AgentRunError as exc:
            if plan is None:
                # The agent never answered (request limit, malformed output):
                # the week is the varied greedy one, and the critic reviews it.
                log.warning("round 1: planner agent failed (%s); using the varied greedy week", exc)
                revised = planner.plan(offered, offers, number_of_meals, varied=True, courses=courses)
                return LoopResult(plan=revised, critique=review(revised, round_number),
                                  rounds=round_number)
            # A revision that failed leaves the last plan standing, with what
            # the critic still holds against it.
            log.warning("round %d/%d: revision failed (%s); keeping the last plan",
                        round_number, max_rounds, exc)
            return LoopResult(plan=plan, critique=verdict, rounds=round_number - 1)
        except RuntimeError as exc:
            if plan is None:
                raise  # no API key, provider down: the caller says the planner is down
            # A revision that failed leaves the last plan standing, with what
            # the critic still holds against it.
            log.warning("round %d/%d: revision failed (%s); keeping the last plan",
                        round_number, max_rounds, exc)
            return LoopResult(plan=plan, critique=verdict, rounds=round_number - 1)
        plan = revised
        if not plan.recipes:
            # Nothing new to review; asking the critic would only pass it.
            verdict = Critique(passed=False, issues=["No candidate recipe could be planned."])
            log.info("round %d/%d: planned nothing — critic not asked", round_number, max_rounds)
            break
        verdict = review(plan, round_number)
        if verdict.passed:
            break
        feedback = _so_far(feedback, verdict)

    return LoopResult(plan=plan, critique=verdict, rounds=round_number)


def _so_far(earlier: Critique | None, latest: Critique) -> Critique:
    """The critic's verdicts added up: every issue, every rejected recipe."""
    if earlier is None:
        return latest
    return Critique(
        passed=False,
        assessment=latest.assessment,
        issues=list(dict.fromkeys([*earlier.issues, *latest.issues])),
        suggestions=latest.suggestions,
        exchange=list(dict.fromkeys([*earlier.exchange, *latest.exchange])),
    )
