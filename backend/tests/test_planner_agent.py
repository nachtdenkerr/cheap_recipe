"""Planner agent wiring — no network, no API key.

These assert the parts pydantic-ai is responsible for on our behalf: that the
tools we registered are the ones offered to the model, that the answer is
validated into a Plan, and that a bad tool argument comes back as a retry the
model can act on rather than an exception that ends the run.
"""

import pytest
from pydantic_ai import ModelRetry, models
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from cheaprecipe.agents.contracts import Ingredient, Quantity, Recipe
from cheaprecipe.agents.planner import (
    PlanChoice,
    PlanningContext,
    _initial_prompt,
    build_planner,
)
from cheaprecipe.llm import DEFAULT_MODEL

RIBOLLITA = Recipe(
    name="Ribollita",
    ingredients=[Ingredient(name="onion", quantity=Quantity(amount=200, unit="g"))],
    servings=2,
    cooking_time=40,
    cuisine=["Italian"],
)


@pytest.fixture(autouse=True)
def no_real_model_requests(monkeypatch):
    """Fail instead of calling OpenRouter if an override is ever missed."""
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)


@pytest.fixture
def agent(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-not-used")
    build_planner.cache_clear()
    # Same arguments as plan_with_agent() passes, so lru_cache hands both the same agent.
    return build_planner(DEFAULT_MODEL)


@pytest.fixture
def deps():
    return PlanningContext(recipes=[RIBOLLITA], offers=[], number_of_meals=1)


def _answers_with_a_plan(messages, info: AgentInfo) -> ModelResponse:
    choice = {"recipes": ["Ribollita"], "reason": "the only candidate"}
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, choice)])


def test_the_three_tools_are_offered(agent):
    assert sorted(agent._function_toolset.tools) == [
        "build_greedy_plan",
        "estimate_leftovers",
        "price_recipe",
    ]


def test_tool_descriptions_come_from_the_docstrings(agent):
    tool = agent._function_toolset.tools["price_recipe"]
    assert "euros" in tool.function_schema.description
    assert "recipe_name" in tool.function_schema.json_schema["properties"]


def test_the_answer_is_validated_into_a_plan(agent, deps):
    with agent.override(model=FunctionModel(_answers_with_a_plan)):
        result = agent.run_sync("plan it", deps=deps)

    assert isinstance(result.output, PlanChoice)
    assert result.output.recipes == ["Ribollita"]
    assert result.usage.requests == 1


def test_an_unknown_recipe_asks_the_model_to_retry(deps):
    """ModelRetry goes back to the model; an exception would end the run."""
    with pytest.raises(ModelRetry, match="Ribollita"):
        deps.find("Spaghetti Carbonara")


def test_a_known_recipe_resolves(deps):
    assert deps.find("Ribollita") is RIBOLLITA


def _answers(*choices):
    """A model that answers these choices in turn, recording the retries it got."""
    choices = list(choices)
    retries = []

    def respond(messages, info: AgentInfo) -> ModelResponse:
        retries.extend(p.content for m in messages for p in m.parts if type(p).__name__ == "RetryPromptPart")
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, choices.pop(0))])

    return FunctionModel(respond), retries


STEW = RIBOLLITA.model_copy(update={"name": "Beef stew"})


def test_an_unknown_or_rejected_recipe_is_sent_back(agent):
    from cheaprecipe.agents.contracts import Critique

    deps = PlanningContext(
        recipes=[RIBOLLITA, STEW], offers=[], number_of_meals=1,
        feedback=Critique(passed=False, issues=["too heavy"], exchange=["Beef stew"]),
    )
    model, retries = _answers(
        {"recipes": ["Carbonara"]},   # not a candidate
        {"recipes": ["Beef stew"]},   # what the critic rejected
        {"recipes": ["Ribollita"]},
    )
    with agent.override(model=model):
        result = agent.run_sync("plan it", deps=deps)
    assert result.output.recipes == ["Ribollita"]
    assert "Carbonara" in str(retries[0]) and "critic asked to replace" in str(retries[-1])


def test_the_agents_choice_is_priced_in_code(monkeypatch, agent):
    from cheaprecipe.agents import planner
    from cheaprecipe.agents.contracts import Item

    onion = Item(name="onion", quantity=Quantity(amount=1, unit="kg"), price=1.0,
                 price_per_unit=1.0, price_per_unit_unit="kg")
    model, _ = _answers({"recipes": ["Ribollita"], "reason": "cheap"})
    monkeypatch.setattr(planner, "using_offers", lambda recipes, offers, minimum=3: recipes)
    with agent.override(model=model):
        plan = planner.plan_with_agent([RIBOLLITA], [onion], 1)
    # The model named a recipe; the cost is the basket's: one 1 kg bag of onions.
    assert [r.name for r in plan.recipes] == ["Ribollita"]
    assert plan.total_cost == 1.0


# --- variety, from the dish labels ------------------------------------------------------

def _dish(name, kind, main):
    return RIBOLLITA.model_copy(update={"name": name, "kind": kind, "main_ingredient": main})


PASTA_A = _dish("Garlic pasta", "pasta", "cauliflower")
PASTA_B = _dish("Red wine spaghetti", "pasta", "mushroom")
TART = _dish("Beetroot tart", "pizza_or_tart", "beetroot")


def test_a_varied_greedy_week_passes_over_a_second_pasta(monkeypatch):
    from cheaprecipe.agents import planner

    monkeypatch.setattr(planner, "using_offers", lambda recipes, offers, minimum=3: recipes)
    assert [r.name for r in planner.plan([PASTA_A, PASTA_B, TART], [], 2, varied=True).recipes] == [
        "Garlic pasta", "Beetroot tart",
    ]
    # Too few kinds to keep the rules: the week stops short rather than repeat.
    assert [r.name for r in planner.plan([PASTA_A, PASTA_B], [], 2, varied=True).recipes] == [
        "Garlic pasta",
    ]


def test_a_repetitive_answer_is_sent_back_when_a_varied_week_exists(agent, monkeypatch):
    from cheaprecipe.agents import planner

    monkeypatch.setattr(planner, "using_offers", lambda recipes, offers, minimum=3: recipes)
    deps = PlanningContext(recipes=[PASTA_A, PASTA_B, TART], offers=[], number_of_meals=2)
    model, retries = _answers(
        {"recipes": ["Garlic pasta", "Red wine spaghetti"]},
        {"recipes": ["Garlic pasta", "Beetroot tart"]},
    )
    with agent.override(model=model):
        result = agent.run_sync("plan it", deps=deps)
    assert result.output.recipes == ["Garlic pasta", "Beetroot tart"]
    assert "2 pasta dishes in one week" in str(retries[0])


def test_the_candidates_show_their_labels():
    deps = PlanningContext(recipes=[PASTA_A, RIBOLLITA], offers=[], number_of_meals=1)
    prompt = _initial_prompt(deps)
    assert "Garlic pasta — 40 min, serves 2, Italian; pasta, built on cauliflower" in prompt
    assert "Ribollita — 40 min, serves 2, Italian\n" in prompt + "\n"  # unlabelled: no label


def test_the_tools_stop_after_the_budget(agent, monkeypatch):
    from cheaprecipe.agents import planner

    monkeypatch.setattr(planner, "using_offers", lambda recipes, offers, minimum=3: recipes)
    deps = PlanningContext(recipes=[PASTA_A, PASTA_B, TART], offers=[], number_of_meals=2)
    calls = {"n": 0}
    answers = []

    def explore_forever(messages, info: AgentInfo) -> ModelResponse:
        # Record what the last tool said; answer only once told to stop.
        returns = [p.content for m in messages for p in m.parts if type(p).__name__ == "ToolReturnPart"]
        if returns and "budget_spent" in returns[-1]:
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,
                                                     {"recipes": ["Garlic pasta", "Beetroot tart"]})])
        calls["n"] += 1
        answers.extend(returns[-1:])
        return ModelResponse(parts=[ToolCallPart("build_greedy_plan", {"exclude": ["Garlic pasta"] * (calls["n"] % 2)})])

    with agent.override(model=FunctionModel(explore_forever)):
        result = agent.run_sync("plan it", deps=deps)
    assert result.output.recipes == ["Garlic pasta", "Beetroot tart"]
    assert calls["n"] == planner.MAX_TOOL_CALLS + 1  # the budget, then the refused call
    assert deps.tool_calls == planner.MAX_TOOL_CALLS + 1


def test_excluding_too_much_is_said_plainly(agent, monkeypatch):
    from cheaprecipe.agents import planner

    monkeypatch.setattr(planner, "using_offers", lambda recipes, offers, minimum=3: recipes)
    deps = PlanningContext(recipes=[PASTA_A, TART], offers=[], number_of_meals=2)
    seen = []

    def exclude_everything(messages, info: AgentInfo) -> ModelResponse:
        returns = [p.content for m in messages for p in m.parts if type(p).__name__ == "ToolReturnPart"]
        if returns:
            seen.append(returns[-1])
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,
                                                     {"recipes": ["Garlic pasta", "Beetroot tart"]})])
        return ModelResponse(parts=[ToolCallPart("build_greedy_plan",
                                                 {"exclude": ["Garlic pasta", "Beetroot tart"]})])

    with agent.override(model=FunctionModel(exclude_everything)):
        agent.run_sync("plan it", deps=deps)
    assert seen[0]["recipes"] == [] and "excludes too much" in seen[0]["note"]
