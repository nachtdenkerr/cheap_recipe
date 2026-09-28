"""Critic agent: reviews a proposed meal plan and returns actionable feedback.

The planner optimises cost and waste; the critic judges what arithmetic
cannot — whether the week is varied, whether the dishes make sense together,
whether they respect the user's notes. Its Critique goes back to the planner
(agents/loop.py), which replaces the recipes it names.

Two rules keep it honest:

- It never does arithmetic. Whether the recipes fit the user's cooking time is
  computed here (`time_conflicts`) and handed to it as facts; a recipe that
  cannot fit is exchanged whatever the model says.
- It can only name recipes that are in the plan, and never one the user
  already chose (`fixed`). Either goes back to the model to correct
  (ModelRetry), like the planner's tools do.

A pydantic-ai agent rather than a raw completion, for the same reasons as the
planner: the Critique schema is enforced, a malformed answer is retried, and
tests can drive it with FunctionModel without an API key.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache

from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.usage import UsageLimits

from cheaprecipe.agents.contracts import Critique, Plan, Recipe, UserPreference
from cheaprecipe.agents.planner import openrouter_model
from cheaprecipe.llm import DEFAULT_MODEL

log = logging.getLogger(__name__)

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

# One answer, plus a couple of corrections.
DEFAULT_REQUEST_LIMIT = 3

SYSTEM_PROMPT = """\
You review a week's meal plan built from discounted supermarket offers.

Judge only what arithmetic cannot:
- variety: dishes that are too similar (same main ingredient, 
  same kind of dish several times) make a dull week;
- whether the dishes make a sensible week together;
- the user's notes, if any.

Cost, leftovers and cooking time are already calculated and given to you as
facts. Do not recompute them or argue with them. Every recipe listed under
"Does not fit the week" must be in `exchange`.

Pass the plan unless something is clearly wrong. When it fails, name the
recipes to replace in `exchange`, by their exact names, and say why in
`issues` and what to look for instead in `suggestions`. Recipes marked as
chosen by the user stay: judge the others against them, never exchange them.
"""


def total_minutes(recipe: Recipe) -> int:
    return recipe.cooking_time + (recipe.preparation_time or 0)


def time_conflicts(
    plan: Plan, availability: list[int] | None, fixed: frozenset[str] = frozenset()
) -> list[str]:
    """Recipes that cannot be fitted into the week's free cooking time.

    Pairs the longest recipe with the freest day, the second longest with the
    second freest, and so on — if any assignment of recipes to days works,
    this one does. Recipes beyond the number of days get no day at all.

    Recipes in `fixed` (chosen by the user) take their days first and are
    never reported: only what the planner added can be exchanged.
    """
    if not availability:
        return []
    days = sorted(availability, reverse=True)
    kept = [r for r in plan.recipes if r.name in fixed]
    added = sorted(
        (r for r in plan.recipes if r.name not in fixed), key=total_minutes, reverse=True
    )
    free = days[len(kept):]
    return [
        recipe.name
        for position, recipe in enumerate(added)
        if total_minutes(recipe) > (free[position] if position < len(free) else 0)
    ]


@dataclass
class CritiqueContext:
    plan: Plan
    user_pref: UserPreference
    conflicts: list[str]
    # Recipes the user already chose; reviewed as part of the week, never exchanged.
    fixed: frozenset[str] = frozenset()


def _prompt(deps: CritiqueContext) -> str:
    """The plan and the facts, compactly — names, times, what each is built on."""
    lines = []
    for recipe in deps.plan.recipes:
        main = ", ".join(i.name for i in recipe.ingredients[:5])
        cuisine = f", {', '.join(recipe.cuisine)}" if recipe.cuisine else ""
        chosen = " (chosen by the user — keep)" if recipe.name in deps.fixed else ""
        lines.append(
            f"- {recipe.name}{chosen} — {total_minutes(recipe)} min, "
            f"serves {recipe.servings}{cuisine}; uses {main}"
        )
    prompt = "The plan:\n" + "\n".join(lines)

    availability = deps.user_pref.week_time_availability
    if availability:
        days = ", ".join(f"{day} {minutes} min" for day, minutes in zip(WEEKDAYS, availability))
        prompt += f"\n\nFree cooking time: {days}"
        if deps.conflicts:
            prompt += "\nDoes not fit the week: " + ", ".join(deps.conflicts)
        else:
            prompt += "\nEvery recipe fits into the week."
    if deps.plan.total_cost is not None:
        prompt += f"\n\nTotal cost: {deps.plan.total_cost:.2f} EUR"
    if deps.user_pref.notes:
        prompt += f"\n\nUser notes: {deps.user_pref.notes}"
    return prompt


@lru_cache(maxsize=1)
def build_critic(model_name: str = DEFAULT_MODEL) -> Agent[CritiqueContext, Critique]:
    os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

    agent = Agent(
        openrouter_model(model_name),
        deps_type=CritiqueContext,
        output_type=Critique,
        instructions=SYSTEM_PROMPT,
        retries=2,
    )

    @agent.output_validator
    def _names_are_in_the_plan(ctx: RunContext[CritiqueContext], critique: Critique) -> Critique:
        exchangeable = {r.name for r in ctx.deps.plan.recipes} - ctx.deps.fixed
        wrong = [name for name in critique.exchange if name not in exchangeable]
        if wrong:
            raise ModelRetry(
                f"Cannot exchange {wrong}: not in the plan, or chosen by the user. "
                "`exchange` takes exact names from: " + ", ".join(sorted(exchangeable))
            )
        return critique

    return agent


def critique(
    plan: Plan,
    user_pref: UserPreference | None = None,
    model_name: str = DEFAULT_MODEL,
    request_limit: int = DEFAULT_REQUEST_LIMIT,
    fixed: frozenset[str] = frozenset(),
) -> Critique:
    """Review `plan`; a failed Critique names the recipes to replace.

    `fixed` names recipes in `plan` the user already chose: they count towards
    the week's variety and time, but only the others can be exchanged.
    """
    user_pref = user_pref or UserPreference()
    deps = CritiqueContext(
        plan=plan,
        user_pref=user_pref,
        conflicts=time_conflicts(plan, user_pref.week_time_availability, fixed),
        fixed=frozenset(fixed),
    )
    result = build_critic(model_name).run_sync(
        _prompt(deps), deps=deps, usage_limits=UsageLimits(request_limit=request_limit)
    )
    return _enforce(result.output, deps.conflicts)


def _enforce(verdict: Critique, conflicts: list[str]) -> Critique:
    """Hold the verdict to the facts: a recipe that does not fit is exchanged,
    and a plan with anything to exchange has not passed."""
    exchange = list(dict.fromkeys([*verdict.exchange, *conflicts]))
    issues = list(verdict.issues)
    for name in conflicts:
        if not any(name in issue for issue in issues):
            issues.append(f"{name} does not fit into the free cooking time this week.")
    passed = verdict.passed and not exchange
    if verdict.passed and not passed:
        log.info("critic passed a plan with recipes to exchange; failing it: %s", exchange)
    return verdict.model_copy(update={"passed": passed, "exchange": exchange, "issues": issues})
