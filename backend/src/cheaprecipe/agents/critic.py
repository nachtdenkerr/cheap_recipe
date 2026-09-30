"""Critic agent: reviews a proposed meal plan and returns actionable feedback.

The planner optimises cost and waste; the critic judges what arithmetic
cannot — what each dish is, whether the dishes make sense together, whether
they respect the user's notes. Its Critique goes back to the planner
(agents/loop.py), which replaces the recipes it names.

Two rules keep it honest:

- It never does arithmetic. It labels each dish (kind, main ingredient) and
  the week's variety is counted from those labels (labels.variety_problems);
  whether the recipes fit the user's cooking time is computed here
  (`time_conflicts`) and handed to it as facts. Either kind of problem is
  exchanged whatever the model says.
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

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.usage import UsageLimits

from cheaprecipe.agents.contracts import Critique, Plan, Recipe, UserPreference
from cheaprecipe.agents.labels import LABELLING, DishLabel, label_of, variety_problems
from cheaprecipe.agents.planner import openrouter_model
from cheaprecipe.calculation.pantry import is_pantry
from cheaprecipe.calculation.schedule import build_week
from cheaprecipe.llm import DEFAULT_MODEL
from cheaprecipe.observability import usage as model_usage

log = logging.getLogger(__name__)

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

# One answer, plus a couple of corrections.
DEFAULT_REQUEST_LIMIT = 3

SYSTEM_PROMPT = f"""\
You review a week's meal plan built from discounted supermarket offers.

First, label every dish in the plan (a dish already labelled in the plan
keeps that label — repeat it):
{LABELLING}
Label carefully and honestly: the week's variety (at most one dish of each
kind, no main ingredient in more than two dishes) is counted from your labels.
Do not count or judge variety yourself.

Then judge what needs taste, and only that:
1. the dishes make a sensible week together — not all heavy, not all the
   same cuisine — and the week grid (which dish is eaten at which meal,
   leftovers included) is one a person would want to eat: a breakfast
   recipe that suits a morning, the same dish not at too many meals. Empty
   meals in the grid are not a reason to reject the week;
2. the user's notes, if any, are respected.
Write your judgement of the week in `assessment` first — also when it
passes, so the user can see why. `passed` is your verdict on these two
alone. When one fails, name the recipes
to replace in `exchange`, by their exact names, say why in `issues`, and what
to look for instead in `suggestions`.

Cost, leftovers and cooking time are calculated and given to you as facts;
do not recompute or argue with them. Recipes marked as chosen by the user
stay: judge the others against them, never exchange them.
"""


class Review(BaseModel):
    """The critic model's answer; turned into a Critique by `_enforce`."""

    dishes: list[DishLabel] = Field(description="Every dish in the plan, labelled.")
    # Before the verdict, so the model reasons first and decides after.
    assessment: str = Field(
        default="",
        description="Two to four sentences: your judgement of this week as a whole — "
        "what works, what does not, and why — before you decide.",
    )
    passed: bool = Field(description="True if the week is sensible and the notes respected.")
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    exchange: list[str] = Field(
        default_factory=list, description="Exact names of recipes to replace."
    )


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
        # What the dish is built on: the pantry staples every recipe shares
        # (salt, oil, garlic…) say nothing about variety.
        main = ", ".join(
            i.name for i in recipe.ingredients if not is_pantry(i.name)
        )[:200]
        cuisine = f", {', '.join(recipe.cuisine)}" if recipe.cuisine else ""
        chosen = " (chosen by the user — keep)" if recipe.name in deps.fixed else ""
        label = label_of(recipe)
        labelled = f"; labelled {label.kind}, built on {label.main_ingredient}" if label else ""
        lines.append(
            f"- {recipe.name}{chosen} — {total_minutes(recipe)} min, "
            f"serves {recipe.servings}{cuisine}; uses {main}{labelled}"
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
    week = build_week(
        deps.plan.recipes, deps.user_pref.household_size, deps.user_pref.meal_types
    )
    prompt += (
        f"\n\nThe week grid, Monday to Friday, for {deps.user_pref.household_size} "
        f"(each cooking feeds servings ÷ household meals, the rest are leftovers):\n"
        + week.describe()
    )
    if deps.plan.total_cost is not None:
        prompt += f"\n\nTotal cost: {deps.plan.total_cost:.2f} EUR"
    if deps.user_pref.notes:
        prompt += f"\n\nUser notes: {deps.user_pref.notes}"
    return prompt


@lru_cache(maxsize=1)
def build_critic(model_name: str = DEFAULT_MODEL) -> Agent[CritiqueContext, Review]:
    os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

    agent = Agent(
        openrouter_model(model_name),
        deps_type=CritiqueContext,
        output_type=Review,
        instructions=SYSTEM_PROMPT,
        retries=2,
    )

    @agent.output_validator
    def _names_are_in_the_plan(ctx: RunContext[CritiqueContext], review: Review) -> Review:
        names = [r.name for r in ctx.deps.plan.recipes]
        exchangeable = set(names) - ctx.deps.fixed
        wrong = [name for name in review.exchange if name not in exchangeable]
        if wrong:
            raise ModelRetry(
                f"Cannot exchange {wrong}: not in the plan, or chosen by the user. "
                "`exchange` takes exact names from: " + ", ".join(sorted(exchangeable))
            )
        labelled = [d.name for d in review.dishes]
        if sorted(labelled) != sorted(names):
            raise ModelRetry(
                "`dishes` must label every recipe in the plan once, by its exact name: "
                + ", ".join(names)
            )
        return review

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
    review = result.output
    usage = result.usage
    model_usage.add("critic", usage)
    # What the model said, as it said it — before code holds it to the facts.
    log.info("critic model (%d request(s), %s tokens): %s — %s",
             usage.requests, usage.total_tokens,
             "passes the week" if review.passed else "rejects the week",
             review.assessment or "(no assessment)")
    for issue in review.issues:
        log.info("critic model issue: %s", issue)
    for suggestion in review.suggestions:
        log.info("critic model suggestion: %s", suggestion)
    if review.exchange:
        log.info("critic model would exchange: %s", review.exchange)
    log.info(
        "critic labels: %s",
        "; ".join(f"{d.name} = {d.kind}/{d.main_ingredient}" for d in review.dishes),
    )
    # A stored label wins over the critic's own: the planner planned with it.
    stored = {r.name: label_of(r) for r in plan.recipes if r.kind is not None}
    relabelled = [
        f"{d.name}: {d.kind}/{d.main_ingredient} -> {stored[d.name].kind}/{stored[d.name].main_ingredient}"
        for d in review.dishes
        if d.name in stored and (d.kind, d.main_ingredient) != (stored[d.name].kind, stored[d.name].main_ingredient)
    ]
    if relabelled:
        log.info("critic labels replaced by the stored ones: %s", "; ".join(relabelled))
    review = review.model_copy(update={"dishes": [stored.get(d.name, d) for d in review.dishes]})
    return _enforce(review, deps.conflicts, [r.name for r in plan.recipes], deps.fixed)


def _enforce(
    review: Review, conflicts: list[str], order: list[str], fixed: frozenset[str] = frozenset()
) -> Critique:
    """The critic's judgement, held to the facts: the week's variety counted
    from its labels, and a recipe that does not fit the time is exchanged.
    A plan with anything to exchange has not passed."""
    issues, suggestions, exchange = variety_problems(review.dishes, order, fixed)
    for issue in issues:
        log.info("variety (counted in code): %s", issue)
    for name in conflicts:
        log.info("cooking time (computed in code): %s does not fit the week", name)
    exchange = list(dict.fromkeys([*review.exchange, *exchange, *conflicts]))
    issues = [*review.issues, *issues]
    for name in conflicts:
        if not any(name in issue for issue in issues):
            issues.append(f"{name} does not fit into the free cooking time this week.")
    passed = review.passed and not exchange
    if review.passed and not passed:
        log.info("critic passed the week's taste; the facts fail it: %s", exchange)
    return Critique(
        passed=passed,
        assessment=review.assessment or None,
        issues=issues,
        suggestions=[*review.suggestions, *suggestions],
        exchange=exchange,
    )
