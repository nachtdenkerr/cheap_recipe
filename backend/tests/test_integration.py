"""End to end, without mocks: load the fixture, then use the app as a user would.

`cheaprecipe load` fills the database from pipeline-shaped files; the API then
plans with the real planner agent and critic in their loop, and serves recipes
and a shopping list priced from those offers. Offer dates are moved to the
current week, so the test does not expire.

The one stand-in is the language model behind the two agents (`agents`
below): a scripted model that uses the real tools the way the instructions
ask. The planner calls build_greedy_plan, excluding what the critic said to
replace, and answers with the recipes it chose; the critic passes, unless a test scripts
its verdict. Everything else — prompts, tools, the loop, the verdict stored —
is the application's own.
"""

import ast
import re
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pydantic_ai import models
from pydantic_ai.messages import (
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import security
from app.main import app
from app.quota import STORE_TZ
from cheaprecipe.agents import critic, planner
from cheaprecipe.db.load import load_files
from cheaprecipe.db.models import Generation
from cheaprecipe.db.session import get_session, init_db, make_engine
from cheaprecipe.llm import DEFAULT_MODEL

FIXTURES = Path(__file__).parent / "fixtures"


class Agents:
    """What the scripted models were asked, and the critic's scripted verdicts."""

    def __init__(self):
        self.planner_prompts: list[str] = []
        self.critic_prompts: list[str] = []
        self.verdicts: list[dict] = []


def _prompt(messages) -> str:
    return next(p.content for m in messages for p in m.parts if isinstance(p, UserPromptPart))


@pytest.fixture(autouse=True)
def agents(monkeypatch):
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)  # never OpenRouter
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-not-used")
    planner.build_planner.cache_clear()
    critic.build_critic.cache_clear()
    seen = Agents()

    def plan(messages, info: AgentInfo) -> ModelResponse:
        planned = [p for m in messages for p in m.parts
                   if isinstance(p, ToolReturnPart) and p.tool_name == "build_greedy_plan"]
        if planned:  # answer with the tool's choice
            answer = {"recipes": planned[-1].content["recipes"], "reason": "cheapest week"}
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, answer)])
        prompt = _prompt(messages)
        seen.planner_prompts.append(prompt)
        # A revision round names what to exclude (planner._feedback_prompt).
        exclude = re.search(r"exclude=(\[.*?\])", prompt)
        args = {"exclude": ast.literal_eval(exclude.group(1))} if exclude else {}
        return ModelResponse(parts=[ToolCallPart("build_greedy_plan", args)])

    def review(messages, info: AgentInfo) -> ModelResponse:
        prompt = _prompt(messages)
        seen.critic_prompts.append(prompt)
        verdict = dict(seen.verdicts.pop(0) if seen.verdicts else {"passed": True})
        # A scripted verdict may label dishes by name ("labels"); the rest get
        # labels that never repeat, leaving variety to the script.
        labels = verdict.pop("labels", {})
        names = [line[2:].split(" — ")[0] for line in prompt.splitlines() if line.startswith("- ")]
        verdict["dishes"] = [
            {"name": n, "kind": labels.get(n, ("other", n))[0], "main_ingredient": labels.get(n, ("other", n))[1]}
            for n in names
        ]
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, verdict)])

    with (
        planner.build_planner(DEFAULT_MODEL).override(model=FunctionModel(plan)),
        critic.build_critic(DEFAULT_MODEL).override(model=FunctionModel(review)),
    ):
        yield seen
    planner.build_planner.cache_clear()
    critic.build_critic.cache_clear()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(security, "_SCRYPT_N", 2**10)
    engine = make_engine("sqlite://", poolclass=StaticPool)
    init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    # This week's offers: the fixture, with its validity moved to today.
    today = datetime.now(STORE_TZ).date()
    frame = pd.read_csv(FIXTURES / "edeka_offers_sample.csv")
    frame["validFrom"] = today.isoformat()
    frame["validTill"] = (today + timedelta(days=4)).isoformat()
    offers = tmp_path / "edeka_offers_classified.csv"
    frame.to_csv(offers, index=False)
    with factory() as session:
        load_files(session, offers, FIXTURES / "edeka_recipes_sample.json", "edeka", "10001604")

    def override():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override
    test_client = TestClient(app)
    test_client.sessions = factory  # for reading back what was stored
    yield test_client
    app.dependency_overrides.clear()


def _user(client) -> dict:
    token = client.post(
        "/auth/signup",
        json={"username": "tester", "email": "tester@example.com", "password": "correct horse battery"},
    ).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    # EDEKA's market finder is out of reach in tests: the search falls back
    # to the branches already known — the one the fixture offers were loaded for.
    [market] = client.get("/markets", headers=headers, params={"q": "10001604"}).json()
    saved = client.post("/auth/me/preferences", headers=headers, json={"homeMarketIds": [market["id"]]})
    assert saved.status_code == 200, saved.text
    return headers


def test_a_week_is_planned_from_the_loaded_offers(client):
    headers = _user(client)

    planned = client.post("/generate", headers=headers)
    assert planned.status_code == 200, planned.text
    titles = {recipe["title"] for recipe in planned.json()}
    # The three meals with 3+ ingredients on offer; "Plain Rice" uses none,
    # the crumble is a dessert and the sushi has no amounts — none are planned.
    assert titles == {"Chicken Tomato Pasta", "Sausage and Apple Bake", "Buttered Onion Pasta"}


# The fixture pool has three meals that use 3+ offers: asking for two leaves
# the agent a choice to make (with none, it is skipped — agents/loop.py).
TWO_OF_THREE = {"numberOfMeals": 2}


def test_the_weekly_plan_is_the_agents_and_the_critic_reviews_it(client, agents):
    headers = _user(client)
    assert client.post("/generate", headers=headers, json=TWO_OF_THREE).status_code == 200

    # The planner agent was given the candidates; the critic the week it made.
    [asked] = agents.planner_prompts
    assert "Chicken Tomato Pasta" in asked
    [reviewed] = agents.critic_prompts
    assert "Buttered Onion Pasta" in reviewed
    with client.sessions() as session:
        week = session.query(Generation).one()
        assert (week.kind, week.model, week.passed) == ("weekly", "agent+critic", True)


def test_with_no_choice_to_make_the_agent_is_skipped_but_the_critic_reviews(client, agents):
    headers = _user(client)
    # Five meals asked, three candidates: every one is in the week anyway.
    assert client.post("/generate", headers=headers).status_code == 200
    assert agents.planner_prompts == []
    assert len(agents.critic_prompts) == 1


def test_the_critics_feedback_goes_back_to_the_agent(client, agents):
    # Round 1: two pasta dishes in one week — the critic asks for one to go.
    agents.verdicts.append({
        "passed": False,
        "issues": ["Two pasta dishes: too similar for one week."],
        "exchange": ["Buttered Onion Pasta"],
    })
    headers = _user(client)
    week = client.post("/generate", headers=headers, json=TWO_OF_THREE)
    assert week.status_code == 200, week.text

    # Round 2 was asked with the critic's issue and the exclusion, and the
    # agent's revised week no longer has the dish; the critic passed it.
    _first, revision = agents.planner_prompts
    assert "Two pasta dishes" in revision and "Buttered Onion Pasta" in revision
    assert {r["title"] for r in week.json()} == {"Chicken Tomato Pasta", "Sausage and Apple Bake"}
    assert len(agents.critic_prompts) == 2
    with client.sessions() as session:
        assert session.query(Generation).one().passed is True


def test_two_pastas_are_caught_from_the_critics_labels(client, agents):
    # The critic only labels the dishes and finds the week sensible; the
    # repetition is counted in code, and the agent replaces the second pasta.
    labels = {
        "Chicken Tomato Pasta": ("pasta", "chicken"),
        "Buttered Onion Pasta": ("pasta", "pasta"),
        "Sausage and Apple Bake": ("casserole_or_bake", "sausage"),
    }
    agents.verdicts.append({"passed": True, "labels": labels})
    headers = _user(client)
    week = client.post("/generate", headers=headers, json=TWO_OF_THREE).json()

    _first, revision = agents.planner_prompts
    assert "2 pasta dishes in one week" in revision
    titles = {r["title"] for r in week}
    assert len(titles & {"Chicken Tomato Pasta", "Buttered Onion Pasta"}) == 1
    assert "Sausage and Apple Bake" in titles


def test_candidates_are_labelled_once_and_the_week_is_varied_from_the_start(client, agents):
    from cheaprecipe.agents import labels
    from cheaprecipe.db.models import RecipeCache

    kinds = {
        "Chicken Tomato Pasta": ("pasta", "chicken"),
        "Buttered Onion Pasta": ("pasta", "pasta"),
        "Sausage and Apple Bake": ("casserole_or_bake", "sausage"),
    }
    asked = []

    def label(messages, info: AgentInfo) -> ModelResponse:
        prompt = _prompt(messages)
        asked.append(prompt)
        names = [line[2:].split(": ")[0] for line in prompt.splitlines() if line.startswith("- ")]
        dishes = [{"name": n, "kind": kinds[n][0], "main_ingredient": kinds[n][1], "course": "main"}
                  for n in names]
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"dishes": dishes})])

    labels.build_labeller.cache_clear()
    with labels.build_labeller(DEFAULT_MODEL).override(model=FunctionModel(label)):
        headers = _user(client)
        week = client.post("/generate", headers=headers, json=TWO_OF_THREE).json()
    labels.build_labeller.cache_clear()

    # The agent saw the labels, and the varied baseline kept to one pasta:
    # the critic passed the first plan.
    [asked_planner] = agents.planner_prompts
    assert "Buttered Onion Pasta" in asked_planner and "pasta, built on" in asked_planner
    titles = {r["title"] for r in week}
    assert len(titles & {"Chicken Tomato Pasta", "Buttered Onion Pasta"}) == 1
    assert len(agents.critic_prompts) == 1
    # Stored, so no recipe is labelled twice.
    with client.sessions() as session:
        stored = {r.name: r.dish_kind for r in session.query(RecipeCache) if r.name in kinds}
    assert stored == {name: kind for name, (kind, _) in kinds.items()}
    assert len(asked) == 1


def test_a_week_the_critic_never_passes_keeps_its_issues(client, agents):
    rejected = {"passed": False, "issues": ["Too much butter."], "exchange": []}
    agents.verdicts.extend([rejected] * 3)
    headers = _user(client)
    assert client.post("/generate", headers=headers, json=TWO_OF_THREE).status_code == 200
    # The rounds ran out (agents/loop.MAX_ROUNDS): the last plan is served,
    # and what is still wrong with it is stored.
    assert len(agents.critic_prompts) == 3
    with client.sessions() as session:
        week = session.query(Generation).one()
        assert (week.passed, week.issues) == (False, ["Too much butter."])


def test_a_recipe_shows_offers_estimates_and_pantry(client):
    headers = _user(client)
    client.post("/generate", headers=headers)
    recipes = {r["title"]: r for r in client.get("/recipes", headers=headers).json()}
    pasta = recipes["Chicken Tomato Pasta"]
    lines = {line["name"]: line for line in pasta["ingredients"]}

    # On offer, priced from the loaded rows.
    assert lines["chicken breast"]["offer"]["title"] == "Frische Hähnchenbrustfilets"
    assert lines["pasta"]["offer"]["priceCents"] == 169
    # Not on offer: a regular-price estimate for a bunch of parsley.
    assert lines["parsley"]["offer"] is None and lines["parsley"]["regularPriceCents"] == 129
    # Pantry: not bought.
    assert lines["olive oil"]["pantry"] and lines["salt"]["pantry"]

    cost = pasta["cost"]
    assert cost["totalCents"] > 0 and cost["estimatedCents"] > 0
    assert cost["unpricedCount"] == 0
    assert pasta["steps"][0] == "Boil the pasta."


def test_the_shopping_list_follows_the_meal_plan(client):
    headers = _user(client)
    client.post("/generate", headers=headers)
    bake = next(r for r in client.get("/recipes", headers=headers).json() if r["title"] == "Sausage and Apple Bake")

    assert client.get("/shopping", headers=headers).json() == []
    client.post(f"/recipes/{bake['id']}/meal-plan", headers=headers)
    items = client.get("/shopping", headers=headers).json()
    by_name = {item["name"]: item for item in items}

    # Offers the bake uses, then the carrots it needs at the regular price.
    assert {"cheese sausage", "onion", "apple", "red wine", "unsalted butter"} <= by_name.keys()
    assert by_name["carrot"]["offer"] is None
    assert by_name["carrot"]["estimatedPriceCents"] == 129
    assert all(item["usedBy"] == ["Sausage and Apple Bake"] for item in items)

    # A tick on the estimated line is saved like any other.
    ticked = client.patch(f"/shopping/{by_name['carrot']['id']}", headers=headers, json={"checked": True})
    assert ticked.status_code == 200
    again = {i["name"]: i["checked"] for i in client.get("/shopping", headers=headers).json()}
    assert again["carrot"] is True


# --- diet and allergens ------------------------------------------------------------

def _set(client, headers, **preferences):
    response = client.post("/auth/me/preferences", headers=headers, json=preferences)
    assert response.status_code == 200, response.text


def test_a_vegetarian_is_never_planned_meat(client):
    headers = _user(client)
    _set(client, headers, dietType="vegetarian")

    planned = client.post("/generate", headers=headers)
    assert planned.status_code == 200, planned.text
    # Chicken pasta and sausage bake are out; the buttered onion pasta is in.
    assert [r["title"] for r in planned.json()] == ["Buttered Onion Pasta"]
    assert planned.json()[0]["dietType"] == "vegetarian"


def test_a_badge_shows_the_recipes_diet_not_the_users(client):
    headers = _user(client)
    planned = client.post("/generate", headers=headers).json()
    diets = {r["title"]: r["dietType"] for r in planned}
    assert diets == {
        "Chicken Tomato Pasta": "normal",
        "Sausage and Apple Bake": "normal",
        "Buttered Onion Pasta": "vegetarian",
    }


def test_a_milk_allergy_removes_everything_with_butter(client):
    headers = _user(client)
    _set(client, headers, allergens=["milk"])
    planned = client.post("/generate", headers=headers).json()
    # Both butter recipes are gone; the chicken pasta has no dairy.
    assert [r["title"] for r in planned] == ["Chicken Tomato Pasta"]
    assert "milk" not in planned[0]["allergens"]


def test_a_vegan_gets_a_clear_answer_not_meat(client):
    headers = _user(client)
    _set(client, headers, dietType="vegan")
    response = client.post("/generate", headers=headers)
    # Only "Plain Rice" is vegan, and it uses none of this week's offers.
    assert response.status_code == 409
    assert response.json()["detail"] == "No recipes use this week's offers"


# --- disliked ingredients, and running out of candidates --------------------------

def test_a_disliked_ingredient_removes_the_recipe(client):
    headers = _user(client)
    _set(client, headers, blackList=["apple"])
    titles = {r["title"] for r in client.post("/generate", headers=headers).json()}
    # "2 apples" is in the bake; the others have none.
    assert titles == {"Chicken Tomato Pasta", "Buttered Onion Pasta"}


def test_an_exhausted_pool_answers_409_without_calling_the_llm(client, monkeypatch):
    headers = _user(client)
    _set(client, headers, dietType="vegetarian", blackList=["apple"])
    week = client.post("/generate", headers=headers).json()
    assert [r["title"] for r in week] == ["Buttered Onion Pasta"]

    def must_not_run(*args, **kwargs):
        raise AssertionError("an LLM step ran with nothing to plan")

    monkeypatch.setattr(planner, "plan_with_agent", must_not_run)
    monkeypatch.setattr(critic, "critique", must_not_run)

    # The one vegetarian meal is already suggested; what is left uses no offers.
    response = client.post("/generate/refine", headers=headers, json={"mode": "replace"})
    assert response.status_code == 409
    assert response.json()["detail"] == "No recipes use this week's offers"
    # A request that planned nothing does not count against the week.
    assert client.get("/generate/quota", headers=headers).json()["remaining"] == 2


# --- top-up: a user who runs short gets recipes fetched for them ------------------

def test_a_short_pool_is_topped_up_for_this_user(client, monkeypatch):
    from cheaprecipe.matching import retrieval

    asked = []

    def spoonacular(ingredients, **kwargs):
        asked.append(kwargs)
        meal = {
            "id": 3001, "title": "Tomato Butter Pasta", "servings": 2, "readyInMinutes": 25,
            "cuisines": [], "dishTypes": ["main course"], "diets": [],
            "vegetarian": True, "vegan": False, "analyzedInstructions": [],
            "extendedIngredients": [
                {"name": name, "aisle": "", "measures": {"metric": {"amount": grams, "unitShort": "g"}}}
                for name, grams in (("pasta", 200), ("cherry tomatoes", 250), ("butter", 30), ("onion", 100))
            ],
        }
        return [meal]

    monkeypatch.setattr(retrieval, "complex_search", spoonacular)
    headers = _user(client)
    _set(client, headers, dietType="vegetarian", blackList=["apple"])

    planned = client.post("/generate", headers=headers)
    assert planned.status_code == 200, planned.text
    # The fixture pool had one vegetarian meal; the top-up found a second.
    assert {r["title"] for r in planned.json()} == {"Buttered Onion Pasta", "Tomato Butter Pasta"}
    # Asked for this user: vegetarian, no apples.
    assert asked[0]["diet"] == "vegetarian" and asked[0]["exclude_ingredients"] == ["apple"]


def test_the_top_up_can_be_switched_off(client, monkeypatch):
    from cheaprecipe.matching import retrieval

    monkeypatch.setenv("RECIPE_TOPUP", "off")
    monkeypatch.setattr(retrieval, "complex_search", lambda *a, **k: pytest.fail("fetched"))
    headers = _user(client)
    _set(client, headers, dietType="vegetarian")
    assert [r["title"] for r in client.post("/generate", headers=headers).json()] == ["Buttered Onion Pasta"]


def test_with_breakfast_chosen_breakfasts_are_searched_and_a_short_course_is_fine(client, monkeypatch):
    from cheaprecipe.matching import retrieval

    asked = []
    monkeypatch.setattr(retrieval, "complex_search", lambda ingredients, **kw: asked.append(kw) or [])
    headers = _user(client)
    _set(client, headers, mealTypes=["breakfast", "lunch", "dinner"])

    week = client.post("/generate", headers=headers)
    assert week.status_code == 200, week.text
    # No breakfast in the pool: one was searched for, none found, and the
    # week is planned with its mains — short of the breakfast, which is fine.
    assert any(call["dish_type"] == "breakfast" for call in asked)
    assert all(r["course"] == "main" for r in week.json())
    assert len(week.json()) == 3


def test_no_pork_means_no_sausage_or_bacon_either(client):
    headers = _user(client)
    _set(client, headers, blackList=["pork"])
    titles = {r["title"] for r in client.post("/generate", headers=headers).json()}
    # "Sausage and Apple Bake" has no word "pork" in it, and is still out.
    assert "Sausage and Apple Bake" not in titles
    assert titles  # the rest of the week is planned


def test_the_critics_judgement_is_there_to_show(client, agents):
    headers = _user(client)
    assert client.get("/generate/review", headers=headers).json() is None  # no plan yet
    rejected = {"passed": False, "issues": ["Too much butter."], "exchange": []}
    agents.verdicts.extend([
        {**rejected, "assessment": "Heavy on butter."},
        rejected,
        {**rejected, "assessment": "Still heavy on butter all week."},
    ])
    client.post("/generate", headers=headers, json=TWO_OF_THREE)

    review = client.get("/generate/review", headers=headers).json()
    assert (review["kind"], review["model"], review["passed"], review["rounds"]) == ("weekly", "agent+critic", False, 3)
    # The verdict on the week that was served: the last round's.
    assert review["assessment"] == "Still heavy on butter all week."
    assert review["issues"] == ["Too much butter."]


# --- planning as a job ------------------------------------------------------------

def test_a_weekly_plan_runs_as_a_job_and_reports_its_steps(client, agents):
    headers = _user(client)
    started = client.post("/generate/jobs/weekly", headers=headers, json=TWO_OF_THREE)
    assert started.status_code == 202
    job_id = started.json()["id"]

    # The test client runs the job before returning; a browser polls.
    job = client.get(f"/generate/jobs/{job_id}", headers=headers).json()
    assert job["status"] == "done" and job["kind"] == "weekly"
    assert len(job["recipes"]) == 2
    assert job["steps"][0] == "Checking this week's offers"
    assert "The planner is choosing recipes" in job["steps"]
    assert "The critic is reviewing the week" in job["steps"]
    # Same as POST /generate: the plan is saved.
    assert {r["title"] for r in client.get("/recipes", headers=headers).json()} == {
        r["title"] for r in job["recipes"]
    }


def test_a_failing_job_says_what_the_request_would_have(client):
    headers = _user(client)
    client.post("/generate", headers=headers)  # this week's plan is made
    job = client.post("/generate/jobs/weekly", headers=headers).json()
    job = client.get(f"/generate/jobs/{job['id']}", headers=headers).json()
    assert (job["status"], job["errorStatus"]) == ("failed", 409)
    assert "already planned" in job["error"]


def test_a_refine_job_returns_the_quota_too(client, agents):
    headers = _user(client)
    client.post("/generate", headers=headers, json=TWO_OF_THREE)
    job = client.post("/generate/jobs/refine", headers=headers, json={"mode": "replace"}).json()
    job = client.get(f"/generate/jobs/{job['id']}", headers=headers).json()
    assert job["status"] == "done" and job["quota"]["remaining"] == 1


def test_a_job_is_only_for_its_user(client):
    headers = _user(client)
    job = client.post("/generate/jobs/weekly", headers=headers).json()
    other = client.post("/auth/signup", json={"username": "other", "email": "o@example.com",
                                              "password": "correct horse battery"}).json()["token"]
    assert client.get(f"/generate/jobs/{job['id']}",
                      headers={"Authorization": f"Bearer {other}"}).status_code == 404
