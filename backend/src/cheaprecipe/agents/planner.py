"""Planner agent: build a weekly meal plan from the retrieved recipes.

Greedy, and deliberately not an LLM: choosing N recipes to minimise cost and
leftovers is arithmetic over a fixed candidate set, which is reproducible,
testable and cheap. The LLM's judgement is spent in the critic instead.

The greedy step is stateful, and that is the whole design. A recipe's cost is
not a property of the recipe — it is the cost of what still has to be bought
*given what the plan has already committed to*. Once one recipe buys a 500 g
bag of onions, every later recipe using onions pays nothing for them and the
leftover shrinks. Scoring each recipe once against an empty basket and taking
the best N would optimise nothing, because the overlap between recipes is
exactly where the savings are.

So: score every remaining candidate against the current basket, commit the
best, rescore. N rounds for N meals.

The arithmetic is not here. Pricing an amount and valuing a leftover live in
calculation/cost.py and calculation/waste.py, whose `compute` functions price
a recipe standalone. This module contributes only the running state: what is
already bought, and therefore what the next recipe still has to pay for.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.usage import UsageLimits

from cheaprecipe.agents.contracts import Critique, Item, Plan, Quantity, Recipe
from cheaprecipe.calculation import cost, waste
from cheaprecipe.config import load_keys, openrouter_api_key
from cheaprecipe.llm import DEFAULT_MODEL

log = logging.getLogger(__name__)

# How many model requests one planning run may make. Bounded because a model
# that keeps asking for prices without ever answering would otherwise spend the
# whole budget; UsageLimits also supports token and cost ceilings. Room for
# the greedy baseline, a few alternatives compared, and the answer.
DEFAULT_REQUEST_LIMIT = 12
# Tool calls one planning run may make; after that every tool tells the model
# to answer. Well inside the request limit, so there is room for the answer
# and a correction or two.
MAX_TOOL_CALLS = 5

# A minute of cooking is worth this many euros of savings — the exchange rate
# that lets time be traded against money in one score. 0.0 ignores time.
DEFAULT_TIME_COST = 0.0

# What the greedy step ranks by first. "cost": cheapest extra spend, with
# leftovers added at their value. "waste": least extra leftover value, cost only
# breaking ties — a recipe that uses up what earlier picks left comes first.
Objective = Literal["cost", "waste"]
DEFAULT_OBJECTIVE: Objective = "cost"

# Ingredient lines a recipe must have covered by offers (or the fridge) to be
# planned at all. The one knob for "how much of a recipe must be on sale":
# 3 left 10 of 24 meals on real EDEKA data (1 left 24, 2 left 17, 4 left 2),
# with the plan built on actual sales. Lower it if a strict profile — a
# cuisine, allergens, a short week — leaves too few candidates.
DEFAULT_MIN_OFFERS = 3


@dataclass
class Purchase:
    """One offer the plan has committed to buying, and how much is spoken for."""

    item: Item
    units: int = 1
    used: float = 0.0

    @property
    def cost(self) -> float:
        return self.item.price * self.units

    @property
    def bought(self) -> float:
        """Total amount purchased, in the offer's own unit."""
        return self.item.quantity.amount * self.units

    @property
    def leftover(self) -> float:
        return waste.leftover(self.bought, self.used)

    @property
    def leftover_value(self) -> float:
        """Leftovers priced in euros, so waste and cost share a currency."""
        return waste.leftover_value(self.bought, self.used, self.item)


@dataclass
class Basket:
    """The running state of the plan: what is bought, what is still unused.

    `project` asks "what would this recipe add?" without mutating; `commit`
    applies it. Keeping those apart is what makes the greedy loop re-scorable.
    Both go through `_simulate`, so they cannot disagree.
    """

    offers: list[Item]
    # Keyed by cost.offer_key.
    purchases: dict[str, Purchase] = field(default_factory=dict)
    unpriced: list[str] = field(default_factory=list)

    @classmethod
    def from_offers(cls, offers: list[Item]) -> Basket:
        # Ingredient -> offer matching is matching/offers.py's, via cost.needs.
        return cls(offers=list(offers))

    @property
    def cost(self) -> float:
        return sum(p.cost for p in self.purchases.values())

    @property
    def leftover_value(self) -> float:
        return sum(p.leftover_value for p in self.purchases.values())

    def _simulate(
        self, recipe: Recipe, servings: int | None
    ) -> tuple[dict[str, Purchase], list[str]]:
        """The purchases this recipe would touch, as they would be after it."""
        scale = servings / recipe.servings if servings and recipe.servings else 1.0
        wanted = cost.needs(recipe, self.offers, scale)
        after: dict[str, Purchase] = {}
        for key, (item, needed) in wanted.amounts.items():
            current = self.purchases.get(key) or Purchase(item=item, units=0)
            units = current.units
            # Use what is already paid for first; buy packs only for the rest.
            shortfall = needed - current.leftover
            if shortfall > 0:
                units += cost.units_needed(
                    Quantity(amount=shortfall, unit=item.quantity.unit), item
                )
            after[key] = Purchase(item=item, units=units, used=current.used + needed)
        return after, wanted.unpriced

    def project(self, recipe: Recipe, servings: int | None = None) -> tuple[float, float]:
        """What this recipe would add: (extra cost, extra leftover value).

        Pure — no mutation, so the same basket can score every candidate.

        Per ingredient: take what is already paid for out of the leftover
        first, then ask cost.units_needed how many further packs the shortfall
        forces. The extra leftover value can be negative: a recipe that uses up
        what an earlier one left makes the plan less wasteful. Ingredients with
        no matching offer add nothing and are collected as unpriced by
        `commit` instead.
        """
        after, _ = self._simulate(recipe, servings)
        extra_cost = extra_waste = 0.0
        for key, purchase in after.items():
            before = self.purchases.get(key)
            extra_cost += purchase.cost - (before.cost if before else 0.0)
            extra_waste += purchase.leftover_value - (before.leftover_value if before else 0.0)
        return extra_cost, extra_waste

    def commit(self, recipe: Recipe, servings: int | None = None) -> None:
        """Apply a recipe: buy what is missing, consume what it uses."""
        after, unpriced = self._simulate(recipe, servings)
        self.purchases.update(after)
        self.unpriced.extend(name for name in unpriced if name not in self.unpriced)

    def grocery_list(self) -> list[Item]:
        """The purchases, as the Items that go on Plan.grocery_list.

        One line per offer: `quantity` is the total bought (packs x pack size)
        and `price` what those packs cost.
        """
        return [
            p.item.model_copy(
                update={
                    "quantity": Quantity(amount=p.bought, unit=p.item.quantity.unit),
                    "price": p.cost,
                }
            )
            for p in self.purchases.values()
            if p.units > 0
        ]

    def leftovers(self) -> list[dict]:
        """What will be left of each pack, for the estimate_leftovers tool."""
        return [
            {
                "name": p.item.name,
                "unit": p.item.quantity.unit,
                "bought": p.bought,
                "used": round(p.used, 3),
                "leftover": round(p.leftover, 3),
                "leftover_value_eur": round(p.leftover_value, 2),
            }
            for p in self.purchases.values()
            if p.units > 0
        ]


def _score(extra_cost: float, extra_waste: float, recipe: Recipe, time_cost: float) -> float:
    """Lower is better. All three terms are euros, so they can simply be added.

    Pricing leftovers rather than counting grams is what makes this sound:
    summing euros, grams and minutes needs arbitrary weights, and the ranking
    then changes if grams become kilograms. calculation/waste.py converts
    waste to the money it represents; time is converted at an explicit
    euros-per-minute rate.
    """
    minutes = recipe.cooking_time + (recipe.preparation_time or 0)
    return extra_cost + extra_waste + time_cost * minutes


def using_offers(
    recipes: list[Recipe], offers: list[Item], minimum: int = DEFAULT_MIN_OFFERS
) -> list[Recipe]:
    """The recipes with at least `minimum` lines covered by offers or fridge items.

    Unpriced ingredients add nothing to a score, so a recipe with nothing on
    sale would otherwise always look cheapest — on real data the greedy plan
    came out at 0 EUR. This app plans from what is discounted; a recipe that
    uses none of it is not a candidate.
    """
    minimum = max(minimum, 1)
    kept = [recipe for recipe in recipes if cost.offer_lines(recipe, offers) >= minimum]
    if len(kept) < len(recipes):
        log.info(
            "%d of %d candidate recipes use fewer than %d offers and are left out",
            len(recipes) - len(kept), len(recipes), minimum,
        )
    return kept


def plan(
    recipes: list[Recipe],
    offers: list[Item],
    number_of_meals: int,
    time_cost: float = DEFAULT_TIME_COST,
    objective: Objective = DEFAULT_OBJECTIVE,
    min_offers: int = DEFAULT_MIN_OFFERS,
    varied: bool = False,
    courses: dict[str, int] | None = None,
) -> Plan:
    """Choose `number_of_meals` recipes that together cost and waste least.

    `courses` is how many of them are breakfasts and how many mains
    (`course_quotas`); without it the course is not looked at. A course with
    too few candidates is left short, not filled with the other.

    `varied` keeps to the week's variety rules (agents/labels.py) where the
    candidates are labelled: a pick that would repeat a kind of dish or
    over-use a main ingredient is passed over, and when only such picks are
    left the week stops short — the critic would reject the repeat anyway.

    `offers` is new relative to the stub: cost cannot come from a Recipe, which
    carries no prices — only the offers know what anything costs.

    Only recipes with `min_offers` lines on offer are considered
    (`using_offers`). `objective` picks what is ranked first; between two that
    rank the same, the one with more of its ingredients on offer wins.
    """
    if number_of_meals < 1:
        raise ValueError(f"number_of_meals must be at least 1, got {number_of_meals}")
    recipes = using_offers(recipes, offers, min_offers)
    share = {id(recipe): cost.offer_share(recipe, offers) for recipe in recipes}
    if len(recipes) < number_of_meals:
        # Not fatal — plan what is possible and let the caller see the shortfall.
        log.warning(
            "only %d candidate recipes for %d meals", len(recipes), number_of_meals
        )

    basket = Basket.from_offers(offers)
    chosen: list[Recipe] = []
    remaining = list(recipes)
    open_slots = dict(courses or {})

    for round_number in range(1, min(number_of_meals, len(remaining)) + 1):
        best: Recipe | None = None
        best_rank: tuple = (float("inf"),)
        best_score = 0.0

        allowed = [
            r for r in remaining
            if (courses is None or open_slots.get(course_of(r), 0) > 0)
            and (not varied or _keeps_variety(chosen, r))
        ]
        if not allowed:
            log.info("no candidate fits the week's courses and variety; stopping at %d meals",
                     len(chosen))
            break
        for candidate in allowed:
            extra_cost, extra_waste = basket.project(candidate)
            score = _score(extra_cost, extra_waste, candidate, time_cost)
            if objective == "waste":
                # Rounded to the cent, so float noise does not decide a tie.
                rank = (round(extra_waste, 2), score, -share[id(candidate)])
            else:
                rank = (score, -share[id(candidate)])
            if rank < best_rank:
                best, best_rank, best_score = candidate, rank, score

        if best is None:  # pragma: no cover — guarded by the loop bound
            break

        basket.commit(best)
        remaining.remove(best)
        chosen.append(best)
        if courses is not None:
            open_slots[course_of(best)] -= 1

        # The marginal cost of each pick is the story of the plan: a second
        # recipe reusing an ingredient should be visibly cheaper than the first.
        log.info(
            # score = extra cost + value of new leftovers (+ time), in euros
            "meal %d: %s (score %.2f, basket now %.2f EUR)",
            round_number, best.name, best_score, basket.cost,
        )

    if basket.unpriced:
        log.warning(
            "%d ingredients have no matching offer and are unpriced, e.g. %s",
            len(basket.unpriced), basket.unpriced[:5],
        )

    return Plan(
        recipes=chosen,
        grocery_list=basket.grocery_list(),
        total_cost=basket.cost,
    )


# With breakfast in the week, this many of its recipes are breakfasts; the
# rest are lunches and dinners.
BREAKFAST_RECIPES = 1


def course_of(recipe: Recipe) -> str:
    """A recipe's course; one of unknown course is planned as a main."""
    return recipe.course or "main"


def course_quotas(number_of_meals: int, meal_types: list[str]) -> dict[str, int]:
    """How many breakfast and main recipes a week of `number_of_meals` has."""
    breakfast = "breakfast" in meal_types
    mains = any(meal in meal_types for meal in ("lunch", "dinner"))
    if breakfast and mains:
        first = min(BREAKFAST_RECIPES, number_of_meals)
        return {"breakfast": first, "main": number_of_meals - first}
    return {"breakfast": number_of_meals} if breakfast else {"main": number_of_meals}


def _keeps_variety(chosen: list[Recipe], candidate: Recipe) -> bool:
    """Whether adding `candidate` keeps the week within the variety rules."""
    from cheaprecipe.agents.labels import label_of, variety_problems

    week = [*chosen, candidate]
    dishes = [label for label in map(label_of, week) if label is not None]
    return not variety_problems(dishes, [r.name for r in week])[2]


def priced(recipes: list[Recipe], offers: list[Item]) -> Plan:
    """These recipes as a Plan: what to buy for them together, and its cost."""
    basket = Basket.from_offers(offers)
    for recipe in recipes:
        basket.commit(recipe)
    return Plan(recipes=list(recipes), grocery_list=basket.grocery_list(), total_cost=basket.cost)


# --- the agent ---------------------------------------------------------------
#
# `plan` above is deterministic and is also exposed to the model as the
# build_greedy_plan tool. The agent exists for the judgement arithmetic cannot
# make: variety across a week, whether a combination is appetising, and
# free-text preferences ("nothing spicy", "something quick on Tuesday"). It
# adjusts a greedy plan rather than composing one from scratch.
#
# Its answer is a choice of recipe names (PlanChoice), not a priced Plan: the
# Plan is built from the names in code (`priced`), so every figure in it is
# computed, and the model never has to copy recipes and prices back out.
#
# The tool schemas are the type hints and the descriptions are the docstrings,
# so the two cannot drift. Plan validation, retries on a malformed answer and
# the tool-call loop are the framework's.

SYSTEM_PROMPT = """\
You plan a week of meals from discounted supermarket offers.

Each candidate shows what kind of dish it is and what it is built on, where
known. A week has at most one dish of each kind and no main ingredient in
more than two dishes.

Start by calling build_greedy_plan, which returns the cheapest, least
wasteful week that keeps to those rules. That week is already a valid
answer. Adjust it only where judgement beats arithmetic: a combination that
does not make a sensible week, or a stated preference. You have
{tool_calls} tool calls in all; when a tool says the budget is spent, answer
straight away with the best week you have seen.

Answer with the exact names of the recipes you choose, and one sentence on
why. Never state a cost or a leftover figure you have not obtained from a tool;
compare combinations with estimate_leftovers.

If a critic reviewed your previous plan, replace every recipe it names, keep
the others unless an issue says otherwise, and address its issues — a
replacement must not repeat the problem (a pasta replaced by another pasta).
Replacements must come from the candidates: build_greedy_plan with `exclude`
finds the cheapest ones that avoid what was rejected, and you may exclude more
to get past a kind of dish that is already in the week.
"""


class PlanChoice(BaseModel):
    """The planner agent's answer."""

    recipes: list[str] = Field(description="Exact names of the chosen candidate recipes.")
    reason: str = Field(default="", description="One sentence on why this week.")


@dataclass
class PlanningContext:
    """Everything the tools need, injected rather than passed through prompts.

    The model never sees this object; it sees recipe *names* and asks a tool
    for anything else. That keeps the transcript small — it is re-sent on every
    round — and keeps the numbers authoritative.
    """

    recipes: list[Recipe]
    offers: list[Item]
    number_of_meals: int
    notes: str | None = None
    # Set on a revision round (agents/loop.py): the plan the critic reviewed,
    # and what it said about it.
    previous: Plan | None = None
    feedback: Critique | None = None
    # How many breakfast and main recipes (course_quotas); None: any course.
    courses: dict[str, int] | None = None
    # Tool calls made in this run (MAX_TOOL_CALLS).
    tool_calls: int = 0

    def spend(self, tool: str) -> dict | None:
        """Count a tool call; past the budget, the answer the tool gives instead.

        Without a budget the model explores for as long as the request limit
        lets it — it once called build_greedy_plan eleven times, one of them
        with every candidate excluded, and never answered.
        """
        self.tool_calls += 1
        if self.tool_calls <= MAX_TOOL_CALLS:
            return None
        log.info("planner tool %s refused: budget of %d calls spent", tool, MAX_TOOL_CALLS)
        return {"budget_spent": (
            f"You have used your {MAX_TOOL_CALLS} tool calls. Answer now with the best "
            "week you have seen — the first build_greedy_plan result is a valid one."
        )}

    def baseline(self, rejected: set[str] = frozenset()) -> Plan:
        """The cheapest varied week the candidates allow, without `rejected`."""
        others = [r for r in self.recipes if r.name not in rejected]
        return plan(others, self.offers, self.number_of_meals, varied=True,
                    courses=self.courses, min_offers=0)

    def find(self, name: str) -> Recipe:
        """Look a candidate up by name, or ask the model to correct itself."""
        for recipe in self.recipes:
            if recipe.name == name:
                return recipe
        raise ModelRetry(
            f"No candidate recipe named {name!r}. Available: "
            + ", ".join(r.name for r in self.recipes)
        )


@lru_cache(maxsize=1)
def openrouter_model(model_name: str = DEFAULT_MODEL) -> OpenAIChatModel:
    """The OpenRouter-backed model, built once.

    Not at import time: config.py deliberately reads no credentials on import
    so the modules stay importable in tests without them.
    """
    load_keys()
    api_key = openrouter_api_key()
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set — add it to .env at the repo root."
        )

    return OpenAIChatModel(
        model_name,
        provider=OpenRouterProvider(
            api_key=api_key,
            # OpenRouter's attribution headers, the same two llm.get_client sets.
            app_url=os.environ.get("OPENROUTER_SITE_URL"),
            app_title=os.environ.get("OPENROUTER_APP_NAME"),
        ),
    )


@lru_cache(maxsize=1)
def build_planner(model_name: str = DEFAULT_MODEL) -> Agent[PlanningContext, PlanChoice]:
    """The planner agent, with its tools registered."""
    # pydantic-ai prints a startup banner straight to the terminal, bypassing
    # the rich logging everything else in the project goes through. Drop this
    # line to get its Logfire/OTel setup hint back.
    os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

    agent = Agent(
        openrouter_model(model_name),
        deps_type=PlanningContext,
        output_type=PlanChoice,
        instructions=SYSTEM_PROMPT.format(tool_calls=MAX_TOOL_CALLS),
        # An answer that fails validation is handed back to the model to fix,
        # rather than raising — the same reason a tool raises ModelRetry.
        retries=2,
    )

    @agent.output_validator
    def _a_valid_choice(ctx: RunContext[PlanningContext], choice: PlanChoice) -> PlanChoice:
        deps = ctx.deps
        for name in choice.recipes:
            deps.find(name)  # ModelRetry, listing the candidates, if unknown
        if len(set(choice.recipes)) != len(choice.recipes):
            raise ModelRetry("Each recipe can be chosen once; remove the repeats.")
        rejected = set(deps.feedback.exchange) if deps.feedback else set()
        kept = rejected.intersection(choice.recipes)
        if kept:
            raise ModelRetry(f"The critic asked to replace {sorted(kept)}; choose others.")
        chosen = [deps.find(name) for name in choice.recipes]
        if deps.courses is not None:
            for course, quota in deps.courses.items():
                count = sum(1 for r in chosen if course_of(r) == course)
                if count > quota:
                    raise ModelRetry(f"At most {quota} {course} recipes; you chose {count}.")
        # As many as the candidates allow: the varied week without the
        # rejected recipes is the least a choice must reach.
        baseline = deps.baseline(rejected)
        if not len(baseline.recipes) <= len(chosen) <= deps.number_of_meals:
            wanted = (str(deps.number_of_meals) if len(baseline.recipes) == deps.number_of_meals
                      else f"{len(baseline.recipes)} to {deps.number_of_meals}")
            raise ModelRetry(f"Choose {wanted} recipes; you chose {len(chosen)}.")
        _check_variety(chosen, baseline)
        return choice

    @agent.tool
    def price_recipe(ctx: RunContext[PlanningContext], recipe_name: str) -> dict:
        """Cost of one recipe on its own, in euros, at current offer prices.

        `pack_cost_eur` is what the packs it needs cost, `used_cost_eur` what
        the amounts it uses are worth. `estimated` lists ingredients not on
        offer, priced at a typical regular price (`estimated_eur` of the used
        cost); `unpriced` lists those with no price at all — not free, just
        unknown. Does not account for ingredients another recipe in the plan
        already buys — use estimate_leftovers or build_greedy_plan for that.
        """
        if stop := ctx.deps.spend("price_recipe"):
            return stop
        recipe = ctx.deps.find(recipe_name)
        costing = cost.compute(recipe, ctx.deps.offers)
        return {
            "pack_cost_eur": round(costing.total, 2),
            "used_cost_eur": round(costing.used, 2),
            "per_serving_eur": round(costing.per_serving, 2),
            "estimated_eur": round(costing.estimated_used, 2),
            "estimated": costing.estimated,
            "unpriced": costing.unpriced,
        }

    @agent.tool
    def estimate_leftovers(
        ctx: RunContext[PlanningContext], recipe_names: list[str]
    ) -> dict:
        """Leftovers, and their value in euros, if these recipes are cooked together.

        Compare combinations with this rather than single recipes: ingredients
        shared between recipes are where the savings are.
        """
        if stop := ctx.deps.spend("estimate_leftovers"):
            return stop
        # Through the Basket, so a later recipe can use up what an earlier one
        # leaves — the point of comparing combinations at all.
        basket = Basket.from_offers(ctx.deps.offers)
        for name in recipe_names:
            basket.commit(ctx.deps.find(name))
        log.info("planner tool estimate_leftovers(%s): %.2f EUR, %.2f EUR left over",
                 recipe_names, basket.cost, basket.leftover_value)
        return {
            "total_cost_eur": round(basket.cost, 2),
            "leftover_value_eur": round(basket.leftover_value, 2),
            "leftovers": basket.leftovers(),
            "unpriced": basket.unpriced,
        }

    @agent.tool
    def build_greedy_plan(
        ctx: RunContext[PlanningContext],
        number_of_meals: int | None = None,
        exclude: list[str] | None = None,
        varied: bool = True,
    ) -> dict:
        """Build a cost- and waste-optimal plan deterministically.

        Use this as the starting point and adjust it, rather than composing a
        plan from scratch. `exclude` drops candidates by name; `varied` keeps
        to the variety rules (one dish per kind, a main ingredient at most
        twice). Returns the chosen recipe names, what they cost together and
        what they leave over.
        """
        if stop := ctx.deps.spend("build_greedy_plan"):
            return stop
        excluded = set(exclude or ())
        wanted = number_of_meals or ctx.deps.number_of_meals
        candidates = [r for r in ctx.deps.recipes if r.name not in excluded]
        result = plan(candidates, ctx.deps.offers, wanted, varied=varied, courses=ctx.deps.courses)
        basket = Basket.from_offers(ctx.deps.offers)
        for recipe in result.recipes:
            basket.commit(recipe)
        answer = {
            "recipes": [r.name for r in result.recipes],
            "total_cost_eur": round(basket.cost, 2),
            "leftover_value_eur": round(basket.leftover_value, 2),
        }
        if len(result.recipes) < min(wanted, len(ctx.deps.baseline().recipes)):
            # Said plainly, or the model keeps trying more exclusions.
            answer["note"] = (
                f"Only {len(result.recipes)} recipes fit when excluding {sorted(excluded)}: "
                "that excludes too much. Exclude less, or answer with an earlier week."
            )
        log.info("planner tool build_greedy_plan(exclude=%s, varied=%s): %s, %.2f EUR",
                 sorted(excluded), varied, answer["recipes"], basket.cost)
        return answer

    return agent


def _check_variety(week: list[Recipe], baseline: Plan) -> None:
    """Send a repetitive week back — when the candidates allow a varied one."""
    from cheaprecipe.agents.labels import label_of, variety_problems

    def problems(recipes: list[Recipe]) -> list[str]:
        labels = [label for label in map(label_of, recipes) if label]
        return variety_problems(labels, [r.name for r in recipes])[0]

    issues = problems(week)
    if not issues or problems(baseline.recipes):
        return  # varied, or the candidates cannot make it so; the critic will say
    raise ModelRetry(
        " ".join(issues) + " Choose a varied week — build_greedy_plan(varied=True) finds one."
    )


def plan_with_agent(
    recipes: list[Recipe],
    offers: list[Item],
    number_of_meals: int,
    notes: str | None = None,
    model_name: str = DEFAULT_MODEL,
    request_limit: int = DEFAULT_REQUEST_LIMIT,
    previous: Plan | None = None,
    feedback: Critique | None = None,
    courses: dict[str, int] | None = None,
) -> Plan:
    """Let the model assemble the plan, with the deterministic work as tools.

    `notes` carries the user's free-text preferences — the one input the greedy
    planner has no way to represent. `previous` and `feedback` make this a
    revision: the critic's verdict on the last plan, for the model to act on.
    """
    deps = PlanningContext(
        # Same rule as the greedy planner: the model never sees a candidate
        # that uses nothing on offer, so it cannot pick one either.
        recipes=using_offers(recipes, offers),
        offers=offers,
        number_of_meals=number_of_meals,
        notes=notes,
        previous=previous,
        feedback=feedback,
        courses=courses,
    )

    if not deps.recipes:
        # Nothing to choose from: a model run would spend tokens to return
        # nothing (it did, before this check).
        log.warning("planner agent skipped: no candidate uses %d+ offers", DEFAULT_MIN_OFFERS)
        return Plan(recipes=[], grocery_list=[], total_cost=0.0)

    result = build_planner(model_name).run_sync(
        _initial_prompt(deps),
        deps=deps,
        usage_limits=UsageLimits(request_limit=request_limit),
    )

    usage = result.usage
    choice = result.output
    log.info(
        "planner agent chose %s in %d request(s), %s tokens: %s",
        choice.recipes, usage.requests, usage.total_tokens, choice.reason,
    )
    return priced([deps.find(name) for name in choice.recipes], offers)


def _initial_prompt(deps: PlanningContext) -> str:
    """The candidate list, as compactly as it can be stated.

    Compact matters: the transcript is re-sent on every round of the tool loop,
    so a verbose candidate list is paid for once per tool call. Names and the
    few fields the model reasons over — it can ask a tool for anything else.
    """
    lines = [
        f"{r.name} — {r.cooking_time} min, serves {r.servings}"
        + (f", {', '.join(r.cuisine)}" if r.cuisine else "")
        + (" (breakfast)" if r.course == "breakfast" else "")
        + (f"; {r.kind.replace('_', ' ')}, built on {r.main_ingredient}" if r.kind else "")
        for r in deps.recipes
    ]
    if deps.courses and set(deps.courses) != {"main"}:
        wanted = " and ".join(
            f"{n} {'breakfast' if course == 'breakfast' else 'lunch or dinner'}"
            for course, n in deps.courses.items() if n
        )
        asked = f"Plan {deps.number_of_meals} recipes — {wanted} —"
    else:
        asked = f"Plan {deps.number_of_meals} meals"
    rejected = set(deps.feedback.exchange) if deps.feedback else set()
    most = len(deps.baseline(rejected).recipes)
    prompt = f"{asked} from these {len(deps.recipes)} candidates:\n" + "\n".join(lines)
    if most < deps.number_of_meals:
        # Said up front, or the model searches the tools for recipes that do
        # not exist (it did: twelve requests, no answer).
        prompt += (
            f"\n\nThe candidates allow a varied week of only {most} recipes: "
            f"plan {most}, not more."
        )
    if deps.notes:
        prompt += f"\n\nUser preferences: {deps.notes}"
    if deps.feedback is not None:
        prompt += "\n\n" + _feedback_prompt(deps.previous, deps.feedback)
    return prompt


def _feedback_prompt(previous: Plan | None, feedback: Critique) -> str:
    """What the critic said about the plans so far, as instructions for this one."""
    parts = ["A critic rejected your previous plan."]
    if previous is not None:
        parts.append("Previous plan: " + ", ".join(r.name for r in previous.recipes))
    if feedback.exchange:
        parts.append(
            "Rejected, do not choose: " + ", ".join(feedback.exchange)
            + f" (call build_greedy_plan with exclude={feedback.exchange!r} for options)"
        )
    if feedback.assessment:
        parts.append(f"The critic's assessment: {feedback.assessment}")
    parts.append("Every issue raised so far — the new plan must have none of them:")
    parts.extend(f"Issue: {issue}" for issue in feedback.issues)
    parts.extend(f"Suggestion: {suggestion}" for suggestion in feedback.suggestions)
    return "\n".join(parts)
