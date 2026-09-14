"""Planner agent wiring — no network, no API key.

These assert the parts pydantic-ai is responsible for on our behalf: that the
tools we registered are the ones offered to the model, that the answer is
validated into a Plan, and that a bad tool argument comes back as a retry the
model can act on rather than an exception that ends the run.
"""

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from cheaprecipe.agents.contracts import Ingredient, Plan, Quantity, Recipe
from cheaprecipe.agents.planner import PlanningContext, build_planner

RIBOLLITA = Recipe(
    name="Ribollita",
    ingredients=[Ingredient(name="onion", quantity=Quantity(amount=200, unit="g"))],
    servings=2,
    cooking_time=40,
    cuisine=["Italian"],
)


@pytest.fixture
def agent(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-not-used")
    build_planner.cache_clear()
    return build_planner()


@pytest.fixture
def deps():
    return PlanningContext(recipes=[RIBOLLITA], offers=[], number_of_meals=1)


def _answers_with_a_plan(messages, info: AgentInfo) -> ModelResponse:
    plan = {
        "recipes": [RIBOLLITA.model_dump(mode="json")],
        "grocery_list": [],
        "total_cost": 3.5,
    }
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, plan)])


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

    assert isinstance(result.output, Plan)
    assert result.output.recipes[0].name == "Ribollita"
    assert result.usage.requests == 1


def test_an_unknown_recipe_asks_the_model_to_retry(deps):
    """ModelRetry goes back to the model; an exception would end the run."""
    with pytest.raises(ModelRetry, match="Ribollita"):
        deps.find("Spaghetti Carbonara")


def test_a_known_recipe_resolves(deps):
    assert deps.find("Ribollita") is RIBOLLITA
