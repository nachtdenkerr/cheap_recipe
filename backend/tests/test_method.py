"""The method editor (agents/method.py), driven by a scripted model — no network."""

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy.orm import Session

from cheaprecipe.agents import method
from cheaprecipe.db.load import check_methods
from cheaprecipe.db.models import RecipeCache
from cheaprecipe.db.session import init_db, make_engine
from cheaprecipe.llm import DEFAULT_MODEL

QUICHE = (
    "cut the leek in stripes and stew it for ten minutes in the buttercut the grapes to halfes "
    "and remove the coresput the milk, the eggs, the leak and the grapes together with the cheese "
    "in a bowl and stir it.bake it for 25 minutes at 200 degree"
)
CLEAN = [
    "Cut the leek into strips and stew it in the butter for ten minutes.",
    "Halve the grapes and remove the seeds.",
    "Put the milk, eggs, leek, grapes and cheese in a bowl and stir.",
    "Bake for 25 minutes at 200 degrees.",
]


@pytest.fixture
def editor(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-not-used")
    method.build_editor.cache_clear()
    yield method.build_editor(DEFAULT_MODEL)
    method.build_editor.cache_clear()


def answering(*answers, seen=None):
    answers = list(answers)

    def respond(messages, info: AgentInfo) -> ModelResponse:
        if seen is not None:
            seen.append(messages)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, answers.pop(0))])

    return FunctionModel(respond)


def test_a_run_on_method_comes_back_as_steps(editor):
    with editor.override(model=answering({"recipes": [{"name": "Puff Paste quiche", "steps": CLEAN}]})):
        assert method.edit_methods({"Puff Paste quiche": QUICHE}) == {"Puff Paste quiche": CLEAN}


def test_an_invented_number_is_sent_back(editor):
    invented = CLEAN[:-1] + ["Bake for 30 minutes at 180 degrees."]
    seen = []
    with editor.override(model=answering(
        {"recipes": [{"name": "Puff Paste quiche", "steps": invented}]},
        {"recipes": [{"name": "Puff Paste quiche", "steps": CLEAN}]},
        seen=seen,
    )):
        assert method.edit_methods({"Puff Paste quiche": QUICHE})["Puff Paste quiche"] == CLEAN
    assert "['180', '30']" in str(seen[1])


def test_every_recipe_must_come_back_with_steps(editor):
    seen = []
    with editor.override(model=answering(
        {"recipes": [{"name": "Puff Paste quiche", "steps": CLEAN}]},
        {"recipes": [{"name": "Puff Paste quiche", "steps": CLEAN}, {"name": "Soup", "steps": ["Heat it."]}]},
        seen=seen,
    )):
        method.edit_methods({"Puff Paste quiche": QUICHE, "Soup": "heat it"})
    assert "Return every recipe once" in str(seen[1])


def test_methods_are_edited_once_and_stored(editor):
    engine = make_engine("sqlite://")
    init_db(engine)
    calls = []

    def respond(messages, info: AgentInfo) -> ModelResponse:
        calls.append(1)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,
                                                 {"recipes": [{"name": "Puff Paste quiche", "steps": CLEAN}]})])

    with Session(engine) as session, editor.override(model=FunctionModel(respond)):
        row = RecipeCache(name="Puff Paste quiche", servings=4, instructions=QUICHE)
        session.add(row)
        session.commit()
        assert check_methods(session, [row]) == 1
        assert row.instructions.splitlines() == CLEAN and row.method_checked
        assert check_methods(session, [row]) == 0  # checked: not asked again
    assert len(calls) == 1
