"""Critic and the planner -> critic loop — no network, no API key."""

import pytest
from pydantic_ai import models
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

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


def neutral_labels(messages) -> list[dict]:
    """A label for every dish in the prompt's plan that never counts as a repeat."""
    prompt = next(p.content for m in messages for p in m.parts if isinstance(p, UserPromptPart))
    names = [line[2:].split(" — ")[0].replace(" (chosen by the user", "")
             for line in prompt.splitlines() if line.startswith("- ")]
    return [{"name": name, "kind": "other", "main_ingredient": name} for name in names]


def answering(*answers, seen=None):
    """A model that returns these Review dicts in turn, recording its prompts.

    An answer without `dishes` gets neutral labels (critic.Review needs them).
    """
    answers = list(answers)

    def respond(messages, info: AgentInfo) -> ModelResponse:
        if seen is not None:
            seen.append(messages)
        answer = dict(answers.pop(0))
        answer.setdefault("dishes", neutral_labels(messages))
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, answer)])

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
    assert "Rejected, do not choose: Tomato pasta" in prompt and "exclude=['Tomato pasta']" in prompt
    assert "Issue: Two pasta dishes." in prompt
    assert "Suggestion: Add a soup." in prompt


def test_a_first_round_prompt_has_no_feedback():
    deps = PlanningContext(recipes=[STEW], offers=[], number_of_meals=1)
    assert "critic" not in _initial_prompt(deps)


# --- the loop -------------------------------------------------------------------

@pytest.fixture
def all_on_offer(monkeypatch):
    """Every candidate counts as using the offers: these tests are about the loop."""
    monkeypatch.setattr(planner, "using_offers", lambda recipes, offers, minimum=3: list(recipes))


@pytest.fixture
def scripted(monkeypatch, all_on_offer):
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


def test_the_loop_reviews_the_whole_week_but_plans_only_the_new(monkeypatch, all_on_offer):
    reviewed = []

    def fake_critique(plan, pref, fixed=frozenset(), **kwargs):
        reviewed.append(([r.name for r in plan.recipes], fixed))
        return Critique(passed=True)

    monkeypatch.setattr(
        planner, "plan_with_agent", lambda recipes, offers, n, **kw: Plan(recipes=[SALAD], grocery_list=[])
    )
    monkeypatch.setattr(critic, "critique", fake_critique)

    result = loop.run([SALAD, PASTA], [], 1, fixed=[STEW])

    assert reviewed == [(["Beef stew", "Quick salad"], frozenset({"Beef stew"}))]
    assert [r.name for r in result.plan.recipes] == ["Quick salad"]


def test_the_loop_returns_the_last_plan_when_rounds_run_out(scripted):
    _, verdicts = scripted
    verdicts.extend([Critique(passed=False, issues=[f"round {i}"]) for i in range(1, 4)])

    result = loop.run([STEW, PASTA], [], 1, max_rounds=3)

    assert result.rounds == 3
    assert result.critique.issues == ["round 3"]
    assert result.plan.recipes == [STEW]


def test_the_loop_does_not_ask_the_critic_about_an_empty_plan(monkeypatch, all_on_offer):
    monkeypatch.setattr(
        planner, "plan_with_agent", lambda recipes, offers, n, **kw: Plan(recipes=[], grocery_list=[])
    )
    monkeypatch.setattr(critic, "critique", lambda *a, **k: pytest.fail("critic asked"))
    result = loop.run([STEW, PASTA, SALAD], [], 2)
    assert result.plan.recipes == [] and result.critique.passed is False
    assert result.rounds == 1


def test_the_llm_planner_is_not_called_without_candidates(monkeypatch):
    monkeypatch.setattr(planner, "build_planner", lambda *a, **k: pytest.fail("model built"))
    plan = planner.plan_with_agent([STEW], [], 2)  # no offers: nothing passes the filter
    assert plan.recipes == []


def test_a_failed_revision_keeps_the_last_plan_and_its_issues(monkeypatch, all_on_offer):
    from pydantic_ai.exceptions import UnexpectedModelBehavior

    rounds = []

    def planner_that_fails_to_revise(recipes, offers, n, **kwargs):
        rounds.append(kwargs)
        if kwargs["feedback"] is not None:
            raise UnexpectedModelBehavior("Exceeded maximum output retries (2)")
        return Plan(recipes=[STEW], grocery_list=[])

    rejection = Critique(passed=False, issues=["dull"], exchange=["Beef stew"])
    monkeypatch.setattr(planner, "plan_with_agent", planner_that_fails_to_revise)
    monkeypatch.setattr(critic, "critique", lambda plan, pref, **kw: rejection)

    result = loop.run([STEW, PASTA], [], 1)
    # The week is served — not a 503 — with what the critic still holds against it.
    assert [r.name for r in result.plan.recipes] == ["Beef stew"]
    assert result.critique is rejection and result.rounds == 1


def test_a_first_round_failure_is_still_an_error(monkeypatch, all_on_offer):
    def down(*args, **kwargs):
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    monkeypatch.setattr(planner, "plan_with_agent", down)
    with pytest.raises(RuntimeError):
        loop.run([STEW, PASTA], [], 1)


def test_the_feedback_adds_up_over_the_rounds(scripted):
    calls, verdicts = scripted
    verdicts.extend([
        Critique(passed=False, issues=["three pasta dishes"], exchange=["Beef stew"]),
        Critique(passed=False, issues=["onion everywhere"], exchange=["Tomato pasta"]),
        Critique(passed=True),
    ])
    loop.run([STEW, PASTA, SALAD], [], 1)
    # Round 3 is told everything: both issues, and both rejected recipes.
    third = calls[2]["feedback"]
    assert third.issues == ["three pasta dishes", "onion everywhere"]
    assert third.exchange == ["Beef stew", "Tomato pasta"]



# --- variety, counted from the critic's labels ------------------------------------------

def _labels(*triples):
    return [critic.DishLabel(name=n, kind=k, main_ingredient=m) for n, k, m in triples]


def test_three_pastas_keep_one_and_exchange_the_others():
    dishes = _labels(
        ("Garlic pasta", "pasta", "cauliflower"),
        ("Red wine spaghetti", "pasta", "mushroom"),
        ("Tart", "pizza_or_tart", "beetroot"),
        ("Orecchiette", "pasta", "sausage"),
    )
    order = ["Garlic pasta", "Red wine spaghetti", "Tart", "Orecchiette"]
    issues, suggestions, exchange = critic.variety_problems(dishes, order)
    assert exchange == ["Red wine spaghetti", "Orecchiette"]  # the first in plan order stays
    assert issues == ["3 pasta dishes in one week (Garlic pasta, Red wine spaghetti, Orecchiette); at most 1."]
    assert "pasta" in suggestions[0]


def test_two_dishes_on_one_main_ingredient_are_fine_three_are_not():
    two = _labels(("Couscous bowl", "grain", "chicken"), ("Shawarma", "tacos_or_wraps", "chicken"))
    assert critic.variety_problems(two, [d.name for d in two]) == ([], [], [])
    three = two + _labels(("Shrimp boil", "soup_or_stew", "Shrimps"), ("Paella", "rice", "shrimp"),
                          ("Shrimp salad", "salad", "shrimp"))
    issues, _, exchange = critic.variety_problems(three, [d.name for d in three])
    assert exchange == ["Shrimp salad"] and "3 dishes built on shrimp" in issues[0]


def test_the_users_own_choice_is_the_one_kept():
    dishes = _labels(("Paella A", "rice", "chicken"), ("Paella B", "rice", "seafood"))
    _, _, exchange = critic.variety_problems(dishes, ["Paella A", "Paella B"], frozenset({"Paella B"}))
    assert exchange == ["Paella A"]


def test_a_repetition_fails_the_plan_even_if_the_model_passed_it(critic_agent):
    labels = [
        {"name": "Beef stew", "kind": "soup_or_stew", "main_ingredient": "beef"},
        {"name": "Tomato pasta", "kind": "pasta", "main_ingredient": "tomato"},
        {"name": "Quick salad", "kind": "pasta", "main_ingredient": "lettuce"},
    ]
    with critic_agent.override(model=answering({"passed": True, "dishes": labels})):
        verdict = critic.critique(PLAN)
    assert verdict.passed is False and verdict.exchange == ["Quick salad"]


def test_every_dish_must_be_labelled(critic_agent):
    seen = []
    partial = {"passed": True, "dishes": [{"name": "Beef stew", "kind": "soup_or_stew", "main_ingredient": "beef"}]}
    with critic_agent.override(model=answering(partial, {"passed": True}, seen=seen)):
        assert critic.critique(PLAN).passed is True
    assert "must label every recipe" in str(seen[1])


def test_the_critics_own_judgement_is_logged_apart_from_what_code_adds(critic_agent, caplog):
    labels = [
        {"name": "Beef stew", "kind": "soup_or_stew", "main_ingredient": "beef"},
        {"name": "Tomato pasta", "kind": "pasta", "main_ingredient": "tomato"},
        {"name": "Quick salad", "kind": "pasta", "main_ingredient": "lettuce"},
    ]
    answer = {"passed": True, "dishes": labels,
              "assessment": "A hearty stew balanced by two light dishes."}
    with caplog.at_level("INFO"), critic_agent.override(model=answering(answer)):
        verdict = critic.critique(PLAN)

    log = caplog.text
    assert "critic model (1 request(s)" in log and "passes the week" in log
    assert "A hearty stew balanced by two light dishes." in log
    assert "variety (counted in code): 2 pasta dishes" in log
    assert verdict.assessment == "A hearty stew balanced by two light dishes." and not verdict.passed


def test_the_assessment_reaches_the_planner():
    feedback = Critique(passed=False, assessment="Too much pasta, nothing light.", issues=["x"])
    deps = PlanningContext(recipes=[STEW], offers=[], number_of_meals=1, feedback=feedback)
    assert "The critic's assessment: Too much pasta, nothing light." in _initial_prompt(deps)
