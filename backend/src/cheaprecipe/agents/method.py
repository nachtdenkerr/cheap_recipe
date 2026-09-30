"""The method editor: a recipe's steps, as Spoonacular sent them, made readable.

Spoonacular's methods come from many sites and some arrive as one run-on
block ("stew it in the buttercut the grapes to halfes…") that no rule can
split. A model reads them and returns clean, numbered steps — one action
each, typos fixed, nothing added.

"Nothing added" is checked, not trusted: every number in the edited steps
(temperatures, minutes, amounts) must be in the original text, and every
recipe must come back with steps. An answer that breaks either is sent back
to the model (ModelRetry), as the other agents' are.

Runs once per recipe; the result is stored (RecipeCache.method_checked).
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from functools import lru_cache

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.usage import UsageLimits

from cheaprecipe.llm import DEFAULT_MODEL
from cheaprecipe.observability import usage as model_usage

log = logging.getLogger(__name__)

INSTRUCTIONS = """\
You edit recipe methods so a home cook can follow them.

For each recipe, rewrite its method as a list of steps:
- one action (or a few tightly linked ones) per step, in the original order;
- split run-on text where one instruction ends and the next begins, even
  when the original has no full stop there;
- fix spelling, spacing and grammar; write plain, imperative English;
- keep every instruction, warning and tip that is in the original;
- add nothing: no ingredients, times, temperatures or amounts that the
  original does not state, and no steps of your own;
- no numbering in the text of a step — the list is the numbering.

Return every recipe you were given, by its exact name.
"""

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


class EditedMethod(BaseModel):
    name: str = Field(description="Exact recipe name.")
    steps: list[str] = Field(description="The method, one action per step.")


class EditedMethods(BaseModel):
    recipes: list[EditedMethod]


@dataclass
class MethodContext:
    # name -> the method as stored
    originals: dict[str, str]


def _numbers(text: str) -> set[str]:
    return {n.replace(",", ".") for n in _NUMBER.findall(text)}


@lru_cache(maxsize=1)
def build_editor(model_name: str = DEFAULT_MODEL) -> Agent[MethodContext, EditedMethods]:
    from cheaprecipe.agents.planner import (
        openrouter_model,  # the planner builds the model
    )

    os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
    agent = Agent(
        openrouter_model(model_name),
        deps_type=MethodContext,
        output_type=EditedMethods,
        instructions=INSTRUCTIONS,
        retries=2,
    )

    @agent.output_validator
    def _faithful(ctx: RunContext[MethodContext], edited: EditedMethods) -> EditedMethods:
        originals = ctx.deps.originals
        names = [r.name for r in edited.recipes]
        if sorted(names) != sorted(originals):
            raise ModelRetry("Return every recipe once, by its exact name: " + "; ".join(originals))
        for recipe in edited.recipes:
            steps = [s.strip() for s in recipe.steps if s.strip()]
            if not steps:
                raise ModelRetry(f"{recipe.name!r} has no steps; rewrite its method as steps.")
            added = _numbers(" ".join(steps)) - _numbers(originals[recipe.name])
            if added:
                raise ModelRetry(
                    f"{recipe.name!r}: the steps state {sorted(added)}, which the original "
                    "method does not. Add nothing — keep only numbers the original gives."
                )
        return edited

    return agent


def edit_methods(methods: dict[str, str], model_name: str = DEFAULT_MODEL) -> dict[str, list[str]]:
    """Clean steps for these methods (name -> text), in one model call."""
    if not methods:
        return {}
    prompt = "\n\n".join(f"Recipe: {name}\nMethod:\n{text}" for name, text in methods.items())
    result = build_editor(model_name).run_sync(
        prompt, deps=MethodContext(originals=dict(methods)),
        usage_limits=UsageLimits(request_limit=4),
    )
    model_usage.add("method editor", result.usage)
    edited = {r.name: [s.strip() for s in r.steps if s.strip()] for r in result.output.recipes}
    log.info(
        "edited the method of %d recipes (%s tokens): %s",
        len(edited), result.usage.total_tokens,
        "; ".join(f"{name} {len(methods[name].splitlines())} -> {len(steps)} steps"
                  for name, steps in edited.items()),
    )
    return edited
