"""What a dish is: its kind and main ingredient — the vocabulary of variety.

A week is varied when it does not repeat a kind of dish (two pastas) or lean
on one main ingredient (shrimp three times). Telling what a dish *is* from its
name and ingredients is judgement, so a model does it: the labeller here,
once per recipe (the label is stored on the recipe and reused), and the
critic for anything still unlabelled. Counting repeats is arithmetic, so code
does it (`variety_problems`) — the same rules for the planner agent, whose
answer is checked against them, and for the critic's verdict.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.usage import UsageLimits

from cheaprecipe.agents.contracts import Recipe
from cheaprecipe.calculation.pantry import is_pantry
from cheaprecipe.llm import DEFAULT_MODEL
from cheaprecipe.observability import usage as model_usage
from cheaprecipe.vocabulary import Course

log = logging.getLogger(__name__)

DishKind = Literal[
    "pasta", "rice", "noodles", "grain", "curry", "soup_or_stew", "burger",
    "tacos_or_wraps", "pizza_or_tart", "salad", "stir_fry", "roast_or_grill",
    "casserole_or_bake", "sandwich",
    # breakfasts
    "eggs", "pancakes_or_waffles", "porridge_or_cereal", "yogurt_or_smoothie", "baked_goods",
    "other",
]

# The week's variety rules.
MAX_PER_KIND = 1
MAX_PER_MAIN_INGREDIENT = 2

# How to label, shared by the labeller and the critic.
LABELLING = """\
- `kind`: what the dish is, whatever its sauce or shape. Spaghetti,
  orecchiette, penne, pappardelle, lasagna and gnocchi are all "pasta"; paella
  and risotto are "rice"; burritos and quesadillas are "tacos_or_wraps". A
  bowl is labelled by its base. Use "other" only when no kind fits.
- `main_ingredient`: the protein, or the vegetable or grain the dish is built
  on and usually named after, in one or two lowercase words ("chicken",
  "shrimp", "sweet potato"). Never an aromatic or a base most recipes share:
  onion, shallot, garlic, ginger, herbs, stock, butter, cream, cheese as a
  topping."""


class DishLabel(BaseModel):
    name: str = Field(description="Exact recipe name.")
    kind: DishKind
    main_ingredient: str


def main_key(ingredient: str) -> str:
    """"Shrimps", "Shrimp " -> "shrimp": labels compared as the same."""
    word = ingredient.strip().lower()
    return word[:-1] if word.endswith("s") and not word.endswith("ss") else word


def label_of(recipe: Recipe) -> DishLabel | None:
    """The stored label a candidate carries, if it has been labelled."""
    if recipe.kind is None:
        return None
    return DishLabel(name=recipe.name, kind=recipe.kind, main_ingredient=recipe.main_ingredient or "")


def variety_problems(
    dishes: list[DishLabel], order: list[str], fixed: frozenset[str] = frozenset()
) -> tuple[list[str], list[str], list[str]]:
    """Issues, suggestions and recipes to exchange for a week that repeats itself.

    Of each repeated kind (or over-used main ingredient) the week keeps the
    user's choices first, then the others in plan order, up to the limit; the
    rest are exchanged.
    """
    issues, suggestions, exchange = [], [], []
    rank = {name: (name not in fixed, order.index(name)) for name in order}

    def over(key, limit: int, label) -> None:
        groups: dict[str, list[str]] = {}
        for dish in dishes:
            value = key(dish)
            if value:
                groups.setdefault(value, []).append(dish.name)
        for value, names in groups.items():
            if len(names) <= limit:
                continue
            names = sorted(names, key=rank.__getitem__)
            issues.append(
                f"{len(names)} {label(value)} in one week ({', '.join(names)}); at most {limit}."
            )
            exchange.extend(n for n in names[limit:] if n not in fixed and n not in exchange)

    over(lambda d: None if d.kind == "other" else d.kind, MAX_PER_KIND,
         lambda kind: f"{kind.replace('_', ' ')} dishes")
    over(lambda d: main_key(d.main_ingredient), MAX_PER_MAIN_INGREDIENT,
         lambda main: f"dishes built on {main}")
    if exchange:
        kinds = sorted({d.kind for d in dishes if d.name not in exchange and d.kind != "other"})
        suggestions.append(
            "Replace them with a kind of dish the week does not have yet (it has: "
            + ", ".join(k.replace("_", " ") for k in kinds) + ")."
        )
    return issues, suggestions, exchange


# --- the labeller -------------------------------------------------------------

INSTRUCTIONS = f"""\
Label each recipe with what kind of dish it is and what it is built on:
{LABELLING}
- `course`: "breakfast" for a dish eaten as a breakfast (eggs, porridge,
  pancakes, granola…), else "main".
Label every recipe given, once, by its exact name.
"""


class CandidateLabel(DishLabel):
    course: Course = Field(description='"breakfast" if it is eaten as a breakfast, else "main".')


class Labels(BaseModel):
    dishes: list[CandidateLabel]


@lru_cache(maxsize=1)
def build_labeller(model_name: str = DEFAULT_MODEL) -> Agent[list[str], Labels]:
    from cheaprecipe.agents.planner import (
        openrouter_model,  # the planner builds the model
    )

    os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
    agent = Agent(
        openrouter_model(model_name),
        deps_type=list,
        output_type=Labels,
        instructions=INSTRUCTIONS,
        retries=2,
    )

    @agent.output_validator
    def _every_recipe_once(ctx: RunContext[list[str]], labels: Labels) -> Labels:
        if sorted(d.name for d in labels.dishes) != sorted(ctx.deps):
            raise ModelRetry("Label every recipe once, by its exact name: " + "; ".join(ctx.deps))
        return labels

    return agent


def label_dishes(recipes: list[Recipe], model_name: str = DEFAULT_MODEL) -> dict[str, CandidateLabel]:
    """Labels for these recipes, by name — one model call for all of them."""
    if not recipes:
        return {}
    lines = [
        f"- {r.name}: " + ", ".join(i.name for i in r.ingredients if not is_pantry(i.name))[:200]
        for r in recipes
    ]
    names = [r.name for r in recipes]
    result = build_labeller(model_name).run_sync(
        "Recipes:\n" + "\n".join(lines), deps=names, usage_limits=UsageLimits(request_limit=4)
    )
    model_usage.add("labeller", result.usage)
    log.info(
        "labelled %d recipes: %s", len(names),
        "; ".join(f"{d.name} = {d.course}, {d.kind}/{d.main_ingredient}" for d in result.output.dishes),
    )
    return {d.name: d for d in result.output.dishes}
