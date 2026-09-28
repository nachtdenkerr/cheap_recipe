"""Critic and the planner -> critic loop — no network, no API key."""

import pytest
from cheaprecipe.agents import critic, loop, planner
from cheaprecipe.agents.contracts import (
    Critique,
    Ingredient,
    Plan,
    Quantity,
    Recipe,
    UserPreference,
)
from cheaprecipe.agents.planner import PlanningContext, _initial_prompt
from cheaprecipe.llm import DEFAULT_MODEL
from pydantic_ai import models
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel


@pytest.fixture(autouse=True)
def no_real_model_requests(monkeypatch):
    """Fail instead of calling OpenRouter if an override is ever missed."""
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)


def recipe(name, minutes, *ingredients, cuisine=()):
    return Recipe(
        name=name,
        ingredients=[
            Ingredient(name=i, quantity=Quantity(amount=100, unit="g")) for i in ingredients
        ],
        servings=2,
        cooking_time=minutes,
        cuisine=list(cuisine),
    )


STEW = recipe("Beef stew", 50, "beef", "carrot")
PASTA = recipe("Tomato pasta", 40, "pasta", "tomato", cuisine=["Italian"])
SALAD = recipe("Quick salad", 20, "lettuce")
PLAN = Plan(recipes=[STEW, PASTA, SALAD], grocery_list=[], total_cost=12.5)


@pytest.fixture
def critic_agent(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-not-used")
    critic.build_critic.cache_clear()
    # Same arguments as critique() passes, so lru_cache hands both the same agent.
    return critic.build_critic(DEFAULT_MODEL)


def answering(*answers, seen=None):
    """A model that returns these Critique dicts in turn, recording its prompts."""
    answers = list(answers)

    def respond(messages, info: AgentInfo) -> ModelResponse:
        if seen is not None:
            seen.append(messages)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, answers.pop(0))])

    return FunctionModel(respond)


# --- deterministic time check -------------------------------------------------

def test_time_conflicts_pair_longest_recipe_with_freest_day():
    # Days sorted: 60, 30, 0. Stew 50 -> 60 fits; pasta 40 -> 30 does not;
    # salad 20 -> a day with no time does not.
    assert critic.time_conflicts(PLAN, [30, 60, 0]) == ["Tomato pasta", "Quick salad"]
    assert critic.time_conflicts(PLAN, [60, 45, 30]) == []
    assert critic.time_conflicts(PLAN, None) == []


def test_more_recipes_than_days_do_not_fit():
    assert critic.time_conflicts(PLAN, [90, 90]) == ["Quick salad"]


# --- the critic -----------------------------------------------------------------

def test_the_critic_gets_the_facts_and_returns_a_critique(critic_agent):
    seen = []
    pref = UserPreference(week_time_availability=[60, 45, 30, 0, 0, 0, 0], notes="no beef")
    verdict_in = {
        "passed": False,
        "issues": ["The user asked for no beef."],
        "suggestions": ["Pick a vegetable dish."],
        "exchange": ["Beef stew"],
    }
    with critic_agent.override(model=answering(verdict_in, seen=seen)):
        verdict = critic.critique(PLAN, pref)

    assert verdict == Critique(**verdict_in)
    prompt = str(seen[0])
    assert "Beef stew — 50 min" in prompt
    assert "Monday 60 min" in prompt and "Every recipe fits" in prompt
    assert "User notes: no beef" in prompt


def test_an_unknown_recipe_name_is_sent_back_to_the_model(critic_agent):
    wrong = {"passed": False, "issues": ["dull"], "exchange": ["Spaghetti Carbonara"]}
    right = {"passed": False, "issues": ["dull"], "exchange": ["Tomato pasta"]}
    seen = []
    with critic_agent.override(model=answering(wrong, right, seen=seen)):
        verdict = critic.critique(PLAN)

    assert verdict.exchange == ["Tomato pasta"]
    assert len(seen) == 2
    assert "Cannot exchange" in str(seen[1])


def test_a_recipe_that_does_not_fit_is_exchanged_whatever_the_model_says(critic_agent):
    pref = UserPreference(week_time_availability=[60, 30, 30])
    with critic_agent.override(model=answering({"passed": True})):
        verdict = critic.critique(PLAN, pref)

    assert verdict.passed is False
    assert verdict.exchange == ["Tomato pasta"]
    assert any("Tomato pasta" in issue for issue in verdict.issues)


def test_a_recipe_the_user_chose_cannot_be_exchanged(critic_agent):
    wrong = {"passed": False, "issues": ["dull"], "exchange": ["Beef stew"]}
    right = {"passed": False, "issues": ["dull"], "exchange": ["Quick salad"]}
    seen = []
    with critic_agent.override(model=answering(wrong, right, seen=seen)):
        verdict = critic.critique(PLAN, fixed=frozenset({"Beef stew"}))

    assert verdict.exchange == ["Quick salad"]
    assert "Beef stew (chosen by the user — keep)" in str(seen[0])


def test_chosen_recipes_take_their_days_first():
    # The stew is the user's and gets the 60-minute day; the pasta, added by the
    # planner, is left with 30 minutes and is the one reported.
    fixed = frozenset({"Beef stew"})
    assert critic.time_conflicts(PLAN, [60, 30, 30], fixed) == ["Tomato pasta"]
    assert critic.time_conflicts(PLAN, [30, 60, 45], frozenset({"Tomato pasta"})) == [
        "Beef stew"
    ]


def test_a_pass_with_nothing_to_exchange_stands(critic_agent):
    with critic_agent.override(model=answering({"passed": True})):
        assert critic.critique(PLAN).passed is True


# --- feedback reaches the planner ---------------------------------------------------

def test_the_planner_prompt_carries_the_critique():
    feedback = Critique(
        passed=False,
        issues=["Two pasta dishes."],
        suggestions=["Add a soup."],
        exchange=["Tomato pasta"],
    )
    deps = PlanningContext(
        recipes=[STEW, PASTA, SALAD], offers=[], number_of_meals=3,
        previous=PLAN, feedback=feedback,
    )
    prompt = _initial_prompt(deps)
    assert "Previous plan: Beef stew, Tomato pasta, Quick salad" in prompt
    assert "Replace: Tomato pasta" in prompt and "exclude=['Tomato pasta']" in prompt
    assert "Issue: Two pasta dishes." in prompt
    assert "Suggestion: Add a soup." in prompt


def test_a_first_round_prompt_has_no_feedback():
    deps = PlanningContext(recipes=[STEW], offers=[], number_of_meals=1)
    assert "critic" not in _initial_prompt(deps)


# --- the loop -------------------------------------------------------------------

@pytest.fixture
def scripted(monkeypatch):
    """Planner and critic stand-ins: record planner calls, answer from a script."""
    calls = []
    verdicts = []

    def fake_planner(recipes, offers, n, **kwargs):
        calls.append(kwargs)
        return Plan(recipes=recipes[:n], grocery_list=[])

    monkeypatch.setattr(planner, "plan_with_agent", fake_planner)
    monkeypatch.setattr(critic, "critique", lambda plan, pref, **kw: verdicts.pop(0))
    return calls, verdicts


def test_the_loop_feeds_a_rejection_back_and_stops_on_a_pass(scripted):
    calls, verdicts = scripted
    rejection = Critique(passed=False, issues=["dull"], exchange=["Beef stew"])
    verdicts.extend([rejection, Critique(passed=True)])

    result = loop.run([STEW, PASTA], [], 1, UserPreference(notes="quick"))

    assert result.rounds == 2 and result.critique.passed
    assert calls[0]["feedback"] is None and calls[0]["previous"] is None
    assert calls[1]["feedback"] is rejection
    assert calls[1]["previous"].recipes[0].name == "Beef stew"
    assert calls[0]["notes"] == "quick"


def test_the_loop_reviews_the_whole_week_but_plans_only_the_new(monkeypatch):
    reviewed = []

    def fake_critique(plan, pref, fixed=frozenset(), **kwargs):
        reviewed.append(([r.name for r in plan.recipes], fixed))
        return Critique(passed=True)

    monkeypatch.setattr(
        planner, "plan_with_agent", lambda recipes, offers, n, **kw: Plan(recipes=[SALAD], grocery_list=[])
    )
    monkeypatch.setattr(critic, "critique", fake_critique)

    result = loop.run([SALAD], [], 1, fixed=[STEW])

    assert reviewed == [(["Beef stew", "Quick salad"], frozenset({"Beef stew"}))]
    assert [r.name for r in result.plan.recipes] == ["Quick salad"]


def test_the_loop_returns_the_last_plan_when_rounds_run_out(scripted):
    _, verdicts = scripted
    verdicts.extend([Critique(passed=False, issues=[f"round {i}"]) for i in range(1, 4)])

    result = loop.run([STEW], [], 1, max_rounds=3)

    assert result.rounds == 3
    assert result.critique.issues == ["round 3"]
    assert result.plan.recipes == [STEW]
