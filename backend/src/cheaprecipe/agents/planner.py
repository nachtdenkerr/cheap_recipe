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
# whole budget; UsageLimits also supports token and cost ceilings.
DEFAULT_REQUEST_LIMIT = 6

# A minute of cooking is worth this many euros of savings — the exchange rate
# that lets time be traded against money in one score. 0.0 ignores time.
DEFAULT_TIME_COST = 0.0


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


def plan(
    recipes: list[Recipe],
    offers: list[Item],
    number_of_meals: int,
    time_cost: float = DEFAULT_TIME_COST,
) -> Plan:
    """Choose `number_of_meals` recipes that together cost and waste least.

    `offers` is new relative to the stub: cost cannot come from a Recipe, which
    carries no prices — only the offers know what anything costs.
    """
    if number_of_meals < 1:
        raise ValueError(f"number_of_meals must be at least 1, got {number_of_meals}")
    if len(recipes) < number_of_meals:
        # Not fatal — plan what is possible and let the caller see the shortfall.
        log.warning(
            "only %d candidate recipes for %d meals", len(recipes), number_of_meals
        )

    basket = Basket.from_offers(offers)
    chosen: list[Recipe] = []
    remaining = list(recipes)

    for round_number in range(1, min(number_of_meals, len(remaining)) + 1):
        best: Recipe | None = None
        best_score = float("inf")

        for candidate in remaining:
            extra_cost, extra_waste = basket.project(candidate)
            score = _score(extra_cost, extra_waste, candidate, time_cost)
            if score < best_score:
                best, best_score = candidate, score

        if best is None:  # pragma: no cover — guarded by the loop bound
            break

        basket.commit(best)
        remaining.remove(best)
        chosen.append(best)

        # The marginal cost of each pick is the story of the plan: a second
        # recipe reusing an ingredient should be visibly cheaper than the first.
        log.info(
            "meal %d: %s (+%.2f EUR, running total %.2f)",
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


# --- the agent ---------------------------------------------------------------
#
# `plan` above is deterministic and is also exposed to the model as the
# build_greedy_plan tool. The agent exists for the judgement arithmetic cannot
# make: variety across a week, whether a combination is appetising, and
# free-text preferences ("nothing spicy", "something quick on Tuesday"). It
# adjusts a greedy plan rather than composing one from scratch — and every
# number it reports comes from a tool, or the plan could not be verified.
#
# The tool schemas are the type hints and the descriptions are the docstrings,
# so the two cannot drift. Plan validation, retries on a malformed answer and
# the tool-call loop are the framework's.

SYSTEM_PROMPT = """\
You plan a week of meals from discounted supermarket offers.

Start by calling build_greedy_plan, which returns the cost- and waste-optimal
selection. Then adjust it only where judgement beats arithmetic: too many
similar dishes, a combination that does not make a sensible week, or a stated
preference.

Never state a cost or a leftover figure you have not obtained from a tool.

If a critic reviewed your previous plan, replace every recipe it names, keep
the others unless an issue says otherwise, and address its issues. Replacements
must come from the candidates: build_greedy_plan with `exclude` finds the
cheapest ones that avoid what was rejected.
"""


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
def build_planner(model_name: str = DEFAULT_MODEL) -> Agent[PlanningContext, Plan]:
    """The planner agent, with its tools registered."""
    # pydantic-ai prints a startup banner straight to the terminal, bypassing
    # the rich logging everything else in the project goes through. Drop this
    # line to get its Logfire/OTel setup hint back.
    os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

    agent = Agent(
        openrouter_model(model_name),
        deps_type=PlanningContext,
        output_type=Plan,
        instructions=SYSTEM_PROMPT,
        # A Plan that fails validation is handed back to the model to fix,
        # rather than raising — the same reason a tool raises ModelRetry.
        retries=2,
    )

    @agent.tool
    def price_recipe(ctx: RunContext[PlanningContext], recipe_name: str) -> dict:
        """Cost of one recipe on its own, in euros, at current offer prices.

        `pack_cost_eur` is what the packs it needs cost, `used_cost_eur` what
        the amounts it uses are worth. `unpriced` lists ingredients no offer
        covers — they are not free, just not on sale. Does not account for
        ingredients another recipe in the plan already buys — use
        estimate_leftovers or build_greedy_plan for that.
        """
        recipe = ctx.deps.find(recipe_name)
        costing = cost.compute(recipe, ctx.deps.offers)
        return {
            "pack_cost_eur": round(costing.total, 2),
            "used_cost_eur": round(costing.used, 2),
            "per_serving_eur": round(costing.per_serving, 2),
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
        # Through the Basket, so a later recipe can use up what an earlier one
        # leaves — the point of comparing combinations at all.
        basket = Basket.from_offers(ctx.deps.offers)
        for name in recipe_names:
            basket.commit(ctx.deps.find(name))
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
    ) -> Plan:
        """Build a cost- and waste-optimal plan deterministically.

        Use this as the starting point and adjust it, rather than composing a
        plan from scratch. `exclude` drops candidates by name.
        """
        excluded = set(exclude or ())
        candidates = [r for r in ctx.deps.recipes if r.name not in excluded]
        return plan(
            candidates,
            ctx.deps.offers,
            number_of_meals or ctx.deps.number_of_meals,
        )

    return agent


def plan_with_agent(
    recipes: list[Recipe],
    offers: list[Item],
    number_of_meals: int,
    notes: str | None = None,
    model_name: str = DEFAULT_MODEL,
    request_limit: int = DEFAULT_REQUEST_LIMIT,
    previous: Plan | None = None,
    feedback: Critique | None = None,
) -> Plan:
    """Let the model assemble the plan, with the deterministic work as tools.

    `notes` carries the user's free-text preferences — the one input the greedy
    planner has no way to represent. `previous` and `feedback` make this a
    revision: the critic's verdict on the last plan, for the model to act on.
    """
    deps = PlanningContext(
        recipes=recipes,
        offers=offers,
        number_of_meals=number_of_meals,
        notes=notes,
        previous=previous,
        feedback=feedback,
    )

    result = build_planner(model_name).run_sync(
        _initial_prompt(deps),
        deps=deps,
        usage_limits=UsageLimits(request_limit=request_limit),
    )

    usage = result.usage
    log.info(
        "planner agent produced %d meals in %d request(s), %s tokens",
        len(result.output.recipes), usage.requests, usage.total_tokens,
    )
    return result.output


def _initial_prompt(deps: PlanningContext) -> str:
    """The candidate list, as compactly as it can be stated.

    Compact matters: the transcript is re-sent on every round of the tool loop,
    so a verbose candidate list is paid for once per tool call. Names and the
    few fields the model reasons over — it can ask a tool for anything else.
    """
    lines = [
        f"{r.name} — {r.cooking_time} min, serves {r.servings}"
        + (f", {', '.join(r.cuisine)}" if r.cuisine else "")
        for r in deps.recipes
    ]
    prompt = (
        f"Plan {deps.number_of_meals} meals from these {len(deps.recipes)} "
        f"candidates:\n" + "\n".join(lines)
    )
    if deps.notes:
        prompt += f"\n\nUser preferences: {deps.notes}"
    if deps.feedback is not None:
        prompt += "\n\n" + _feedback_prompt(deps.previous, deps.feedback)
    return prompt


def _feedback_prompt(previous: Plan | None, feedback: Critique) -> str:
    """The critic's verdict on the last plan, as instructions for this one."""
    parts = ["A critic rejected your previous plan."]
    if previous is not None:
        parts.append("Previous plan: " + ", ".join(r.name for r in previous.recipes))
    if feedback.exchange:
        parts.append(
            "Replace: " + ", ".join(feedback.exchange)
            + f" (call build_greedy_plan with exclude={feedback.exchange!r} for options)"
        )
    parts.extend(f"Issue: {issue}" for issue in feedback.issues)
    parts.extend(f"Suggestion: {suggestion}" for suggestion in feedback.suggestions)
    return "\n".join(parts)
