"""API endpoints against an in-memory database — no network, no API key."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import security
from app.main import app
from app.quota import STORE_TZ, week_bounds
from cheaprecipe.agents import critic, planner
from cheaprecipe.agents.contracts import Critique, Plan
from cheaprecipe.db.models import (
    Address,
    CanonicalIngredient,
    Generation,
    GenerationItem,
    Offer,
    RecipeCache,
    RecipeIngredient,
    Supermarket,
    User,
    UserPreference,
)
from cheaprecipe.db.session import get_session, init_db, make_engine

PASSWORD = "correct horse battery"


@pytest.fixture
def db(monkeypatch):
    # Cheap scrypt parameters: the production cost is deliberate, and slow.
    monkeypatch.setattr(security, "_SCRYPT_N", 2**10)
    engine = make_engine("sqlite://", poolclass=StaticPool)
    init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override
    yield factory
    app.dependency_overrides.clear()


@pytest.fixture
def client(db):
    # No `with`: the lifespan would create tables in the real database.
    return TestClient(app)


def _signup(client, email="nga@example.com", username="nga"):
    response = client.post(
        "/auth/signup",
        json={"username": username, "email": email, "password": PASSWORD, "name": "Nga"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _seed_plan(factory, email="nga@example.com"):
    """One EDEKA plan: a gnocchi recipe using two offers, one pantry line."""
    with factory() as session:
        edeka = Supermarket(name="EDEKA")
        store = Address(supermarket=edeka, market_id="10001")
        pumpkin = CanonicalIngredient(
            name="pumpkin", kcal_per_100=26, protein_per_100=1, carbs_per_100=6.5,
            fat_per_100=0.1,
        )
        butter = CanonicalIngredient(
            name="butter", kcal_per_100=717, protein_per_100=0.9, carbs_per_100=0.1,
            fat_per_100=81, allergens=["milk"],
        )
        today = datetime.now(STORE_TZ).date()
        week_end = today + timedelta(days=3)
        pumpkin_offer = Offer(
            address=store, title="Hokkaido Kürbis", category="Obst & Gemüse",
            price=1.11, quantity_amount=1, quantity_unit="kg", quantity_basis="package",
            valid_from=today, valid_till=week_end, canonical_ingredient=pumpkin,
            ingredient_en="hokkaido pumpkin",
        )
        butter_offer = Offer(
            address=store, title="Weihenstephan Butter", category="Molkerei & Käse",
            price=1.79, quantity_amount=250, quantity_unit="g", quantity_basis="package",
            valid_from=today, valid_till=week_end, canonical_ingredient=butter,
            ingredient_en="butter",
        )
        recipe = RecipeCache(
            name="Pumpkin Gnocchi", servings=2, total_time=35, diet_type="vegetarian",
            instructions="Roast the pumpkin.\n\nBrown the butter.",
            ingredients=[
                RecipeIngredient(name="pumpkin", amount=500, unit="g", canonical_ingredient=pumpkin),
                RecipeIngredient(name="butter", amount=50, unit="g", canonical_ingredient=butter),
                RecipeIngredient(name="sage", amount=8, unit="leaves"),
                RecipeIngredient(name="salt", amount=1, unit="g"),
                RecipeIngredient(name="carrots", amount=300, unit="g"),
            ],
        )
        user = session.query(User).filter_by(email=email).one()
        _set_home(user, store)
        generation = Generation(
            user=user, diet_type="vegetarian", recipes=[recipe],
            items=[
                GenerationItem(offer=pumpkin_offer, amount=500, unit="g"),
                GenerationItem(offer=butter_offer, amount=50, unit="g"),
                GenerationItem(name="sage", amount=8, unit="leaves"),
                GenerationItem(name="carrot"),
            ],
        )
        session.add_all([edeka, generation])
        session.commit()
        return recipe.id


def _set_home(user, *branches):
    user.preference = user.preference or UserPreference()
    user.preference.home_markets = list(branches)


def test_signup_login_and_me(client):
    _signup(client)

    wrong = client.post("/auth/login", json={"email": "nga@example.com", "password": "nope"})
    assert wrong.status_code == 401

    login = client.post("/auth/login", json={"email": "NGA@example.com", "password": PASSWORD})
    assert login.status_code == 200
    token = login.json()["token"]

    me = client.get("/auth/me", headers=_auth(token)).json()
    assert me == {
        "name": "Nga", "email": "nga@example.com", "dietType": "normal",
        "householdSize": 1, "weeklyBudgetCents": None, "allergens": [],
        "homeMarkets": [], "cuisines": [], "whiteList": [], "blackList": [],
        "healthGoal": None, "age": None, "gender": None, "weekTimeAvailability": None,
            "mealTypes": ["lunch", "dinner"],
    }


def test_duplicate_signup_conflicts(client):
    _signup(client)
    response = client.post(
        "/auth/signup",
        json={"username": "other", "email": "nga@example.com", "password": PASSWORD},
    )
    assert response.status_code == 409


def test_endpoints_require_a_valid_token(client):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/recipes", headers=_auth("1.9999999999.forged")).status_code == 401


def test_update_preferences(client, db):
    token = _signup(client)["token"]
    with db() as session:
        branch = Address(supermarket=Supermarket(name="EDEKA"), market_id="10001604",
                         name="EDEKA Frank", city="Flein")
        session.add(branch)
        session.commit()
        branch_id = branch.id

    response = client.post(
        "/auth/me/preferences",
        headers=_auth(token),
        json={"dietType": "vegan", "householdSize": 2, "allergens": ["nuts"],
              "homeMarketIds": [branch_id], "cuisines": ["Italian"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["dietType"], body["householdSize"]) == ("vegan", 2)
    assert body["homeMarkets"] == [{
        "id": branch_id, "chain": "edeka", "marketId": "10001604", "name": "EDEKA Frank",
        "street": None, "postalCode": None, "city": "Flein",
    }]
    assert body["allergens"] == ["nuts"] and body["cuisines"] == ["Italian"]

    for bad in ({"dietType": "ketogenic"}, {"allergens": ["pollen"]}):
        rejected = client.post("/auth/me/preferences", headers=_auth(token), json=bad)
        assert rejected.status_code == 422, bad

    unknown = client.post("/auth/me/preferences", headers=_auth(token), json={"homeMarketIds": [999]})
    assert unknown.status_code == 422
    too_many = client.post("/auth/me/preferences", headers=_auth(token), json={"homeMarketIds": [1, 2, 3, 4]})
    assert too_many.status_code == 422


def test_ingredient_lists_are_cleaned_and_saved(client):
    token = _signup(client)["token"]
    response = client.post(
        "/auth/me/preferences",
        headers=_auth(token),
        json={"whiteList": [" Pumpkin", "pumpkin", "", "Leek"], "blackList": ["Coriander"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["whiteList"] == ["pumpkin", "leek"]

    # Fields left out are untouched; an empty list clears.
    client.post("/auth/me/preferences", headers=_auth(token), json={"whiteList": []})
    me = client.get("/auth/me", headers=_auth(token)).json()
    assert (me["whiteList"], me["blackList"]) == ([], ["coriander"])


def test_recipes_before_any_plan_are_empty(client):
    token = _signup(client)["token"]
    assert client.get("/recipes", headers=_auth(token)).json() == []
    assert client.get("/shopping", headers=_auth(token)).json() == []


def test_recipes_are_costed_against_the_plan(client, db):
    token = _signup(client)["token"]
    recipe_id = _seed_plan(db)

    recipes = client.get("/recipes", headers=_auth(token)).json()
    assert [r["id"] for r in recipes] == [str(recipe_id)]

    recipe = client.get(f"/recipes/{recipe_id}", headers=_auth(token)).json()
    assert recipe["dietType"] == "vegetarian"
    assert (recipe["isFavourite"], recipe["inMealPlan"]) == (False, False)
    assert recipe["allergens"] == ["milk"]
    assert recipe["steps"] == ["Roast the pumpkin.", "Brown the butter."]
    assert recipe["minutes"] == 35

    pumpkin, _butter, sage, salt, carrots = recipe["ingredients"]
    assert pumpkin["offer"]["priceCents"] == 111 and not pumpkin["pantry"]
    # Carrots are not on offer: estimated at the regular price of a 1 kg bag.
    assert carrots["offer"] is None and carrots["regularPriceCents"] == 129
    # Sage has a regular price, but "8 leaves" does not convert: unpriced.
    assert sage == {
        "name": "sage", "amount": "8 leaves", "offer": None, "pantry": False,
        "regularPriceCents": None,
    }
    assert salt["pantry"] is True
    assert recipe["cost"]["unpricedCount"] == 1

    # Half the pumpkin (0.555) + a fifth of the butter (0.358), exact, plus
    # 300 g of a 1.29 kg-bag of carrots (0.387), estimated.
    assert recipe["cost"]["totalCents"] == 130
    assert recipe["cost"]["estimatedCents"] == 39
    assert recipe["cost"]["perServingCents"] == 65
    assert recipe["cost"]["leftoverCents"] == 111 + 179 - 91

    # (500 g × 26 + 50 g × 717) / 100 / 2 servings
    assert recipe["nutrition"]["kcal"] == round((130 + 358.5) / 2)


def test_recipe_from_someone_elses_plan_is_not_found(client, db):
    _signup(client)
    recipe_id = _seed_plan(db)
    other = _signup(client, email="other@example.com", username="other")["token"]
    assert client.get(f"/recipes/{recipe_id}", headers=_auth(other)).status_code == 404


def test_favourites_are_saved_on_the_preferences(client, db):
    token = _signup(client)["token"]
    recipe_id = _seed_plan(db)

    hearted = client.post(f"/recipes/{recipe_id}/favourite", headers=_auth(token))
    assert hearted.status_code == 200 and hearted.json()["isFavourite"] is True
    # Idempotent: a second heart does not duplicate the row.
    client.post(f"/recipes/{recipe_id}/favourite", headers=_auth(token))
    with db() as session:
        user = session.query(User).one()
        assert [r.id for r in user.preference.favourite_recipes] == [recipe_id]

    assert client.get("/recipes", headers=_auth(token)).json()[0]["isFavourite"] is True
    unhearted = client.delete(f"/recipes/{recipe_id}/favourite", headers=_auth(token))
    assert unhearted.json()["isFavourite"] is False


def test_favouriting_a_recipe_never_suggested_is_not_found(client, db):
    _signup(client)
    recipe_id = _seed_plan(db)
    other = _signup(client, email="other@example.com", username="other")["token"]
    assert client.post(f"/recipes/{recipe_id}/favourite", headers=_auth(other)).status_code == 404


def test_only_planned_recipes_fill_the_shopping_list(client, db):
    token = _signup(client)["token"]
    recipe_id = _seed_plan(db)
    assert client.get("/shopping", headers=_auth(token)).json() == []

    planned = client.post(f"/recipes/{recipe_id}/meal-plan", headers=_auth(token))
    assert planned.status_code == 200 and planned.json()["inMealPlan"] is True
    assert len(client.get("/shopping", headers=_auth(token)).json()) == 4

    client.delete(f"/recipes/{recipe_id}/meal-plan", headers=_auth(token))
    assert client.get("/shopping", headers=_auth(token)).json() == []


def test_shopping_list_and_ticking_items(client, db):
    token = _signup(client)["token"]
    recipe_id = _seed_plan(db)
    client.post(f"/recipes/{recipe_id}/meal-plan", headers=_auth(token))

    items = client.get("/shopping", headers=_auth(token)).json()
    # Everything but the salt (pantry): two offers, then two bought regular.
    assert [i["name"] for i in items] == ["hokkaido pumpkin", "butter", "sage", "carrot"]
    assert [i["offer"]["title"] for i in items[:2]] == ["Hokkaido Kürbis", "Weihenstephan Butter"]
    assert all(i["quantity"] == 1 and i["usedBy"] == ["Pumpkin Gnocchi"] for i in items)
    sage, carrot = items[2:]
    assert (sage["offer"], sage["amount"], sage["estimatedPriceCents"]) == (None, "8 leaves", None)
    assert (carrot["amount"], carrot["estimatedPriceCents"]) == ("300 g", 129)

    ticked = client.patch(
        f"/shopping/{items[0]['id']}", headers=_auth(token), json={"checked": True}
    )
    assert ticked.status_code == 200 and ticked.json()["checked"] is True

    assert client.post("/shopping/uncheck-all", headers=_auth(token)).status_code == 204
    assert not any(i["checked"] for i in client.get("/shopping", headers=_auth(token)).json())


def test_generate_without_data_is_a_conflict(client):
    token = _signup(client)["token"]
    assert client.post("/generate", headers=_auth(token)).status_code == 409


# --- refine: follow-up requests against this week's plan ---------------------

def _add_candidates(factory, *names, to_current_plan=False):
    """Recipes in the cache the planner may pick; optionally suggested already."""
    with factory() as session:
        rows = [RecipeCache(name=name, servings=2, total_time=20) for name in names]
        session.add_all(rows)
        if to_current_plan:
            generation = session.query(Generation).one()
            generation.recipes.extend(rows)
        session.commit()
        return [row.id for row in rows]


class _Calls(list):
    """The planner's calls, with the critic's reviews and script alongside."""


@pytest.fixture
def fake_planner(monkeypatch):
    """Stand-ins for the LLM planner and the critic.

    The planner takes the first N candidates and records its calls; the critic
    records what it reviewed and passes, unless `verdicts` holds a scripted one.
    """
    calls = _Calls()
    reviews = []
    verdicts = []

    def fake_plan(recipes, offers, number_of_meals, **kwargs):
        calls.append({"recipes": recipes, "offers": offers, "n": number_of_meals, **kwargs})
        return Plan(recipes=recipes[:number_of_meals], grocery_list=[], total_cost=0.0)

    def fake_critique(plan, user_pref, fixed=frozenset(), **kwargs):
        reviews.append({"plan": plan, "user_pref": user_pref, "fixed": fixed})
        return verdicts.pop(0) if verdicts else Critique(passed=True)

    monkeypatch.setattr(planner, "plan", fake_plan)
    monkeypatch.setattr(planner, "plan_with_agent", fake_plan)
    monkeypatch.setattr(critic, "critique", fake_critique)
    # These candidates have no ingredients; routing, not the offer filter, is
    # under test here (that has its own tests in test_calculation/integration).
    monkeypatch.setattr(planner, "using_offers", lambda recipes, offers, minimum=3: recipes)
    calls.reviews = reviews
    calls.verdicts = verdicts
    return calls


def test_quota_before_and_after_the_weekly_plan(client, db):
    token = _signup(client)["token"]
    quota = client.get("/generate/quota", headers=_auth(token)).json()
    assert (quota["used"], quota["limit"], quota["remaining"]) == (0, 2, 2)
    assert quota["weeklyPlanDone"] is False

    _seed_plan(db)
    assert client.get("/generate/quota", headers=_auth(token)).json()["weeklyPlanDone"] is True


def test_weekly_plan_is_once_per_week(client, db):
    token = _signup(client)["token"]
    _seed_plan(db)
    response = client.post("/generate", headers=_auth(token))
    assert response.status_code == 409
    assert "already planned" in response.json()["detail"]


def test_refine_keeps_planned_and_replaces_the_rest(client, db, fake_planner):
    token = _signup(client)["token"]
    kept = _seed_plan(db)
    [dropped] = _add_candidates(db, "Dropped Soup", to_current_plan=True)
    [fresh, _spare] = _add_candidates(db, "Fresh Salad", "Spare Stew")

    client.post(f"/recipes/{kept}/meal-plan", headers=_auth(token))
    butter = client.get("/shopping", headers=_auth(token)).json()[1]
    client.patch(f"/shopping/{butter['id']}", headers=_auth(token), json={"checked": True})

    response = client.post("/generate/refine", headers=_auth(token), json={"mode": "replace"})
    assert response.status_code == 200, response.text
    body = response.json()

    # One unplanned recipe, so one replacement, drawn from recipes not seen this week.
    assert fake_planner[0]["n"] == 1
    assert dropped not in {int(r.external_id) for r in fake_planner[0]["recipes"]}
    assert [r["id"] for r in body["recipes"]] == [str(kept), str(fresh)]
    assert [r["inMealPlan"] for r in body["recipes"]] == [True, False]
    assert body["quota"]["remaining"] == 1

    # The planned recipe's shopping lines came along, tick included.
    items = client.get("/shopping", headers=_auth(token)).json()
    assert [(i["name"], i["checked"]) for i in items] == [
        ("hokkaido pumpkin", False), ("butter", True), ("sage", False), ("carrot", False),
    ]


def test_pantry_items_reach_the_planner_as_free_items(client, db, fake_planner):
    token = _signup(client)["token"]
    _seed_plan(db)
    _add_candidates(db, "Leek Omelette")

    missing = client.post("/generate/refine", headers=_auth(token), json={"mode": "pantry"})
    assert missing.status_code == 422

    response = client.post(
        "/generate/refine", headers=_auth(token),
        json={"mode": "pantry", "pantryItems": ["Eggs", "leek"], "count": 1},
    )
    assert response.status_code == 200, response.text
    free = [o for o in fake_planner[0]["offers"] if o.price == 0]
    assert [o.name for o in free] == ["eggs", "leek"]
    assert all(o.offer_id is None for o in free)


def test_a_note_goes_to_the_llm_planner(client, db, monkeypatch, fake_planner):
    token = _signup(client)["token"]
    _seed_plan(db)
    # Two for the one slot: with a choice to make, the agent makes it.
    _add_candidates(db, "Mild Curry", "Lentil Soup")
    monkeypatch.setattr(planner, "plan", lambda *a, **k: pytest.fail("greedy path used"))

    client.post(
        "/generate/refine", headers=_auth(token),
        json={"mode": "replace", "note": "  nothing spicy  "},
    )
    assert fake_planner[0]["notes"] == "nothing spicy"


def test_refine_quota_is_two_per_week_and_resets(client, db, fake_planner):
    token = _signup(client)["token"]
    _seed_plan(db)
    _add_candidates(db, "A", "B", "C")

    for _ in range(2):
        response = client.post(
            "/generate/refine", headers=_auth(token), json={"mode": "replace", "count": 1}
        )
        assert response.status_code == 200, response.text
    third = client.post("/generate/refine", headers=_auth(token), json={"mode": "replace"})
    assert third.status_code == 429

    # Move the refines into last week: the quota is full again.
    with db() as session:
        for generation in session.query(Generation).filter_by(kind="refine"):
            generation.created_at -= timedelta(days=7)
        session.commit()
    assert client.get("/generate/quota", headers=_auth(token)).json()["remaining"] == 2


def test_failed_refine_does_not_use_the_quota(client, db, monkeypatch):
    token = _signup(client)["token"]
    _seed_plan(db)
    _add_candidates(db, "Anything")

    def unavailable(*args, **kwargs):
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    monkeypatch.setattr(planner, "plan_with_agent", unavailable)
    monkeypatch.setattr(planner, "using_offers", lambda recipes, offers, minimum=3: recipes)
    response = client.post("/generate/refine", headers=_auth(token), json={"mode": "replace"})
    assert response.status_code == 503
    assert client.get("/generate/quota", headers=_auth(token)).json()["remaining"] == 2


def test_refine_needs_a_plan_this_week(client, fake_planner):
    token = _signup(client)["token"]
    response = client.post("/generate/refine", headers=_auth(token), json={"mode": "replace"})
    assert response.status_code == 409


def test_week_bounds_survive_the_dst_switch():
    # DST starts in Germany on Sunday 29 March 2026.
    start, end = week_bounds(datetime(2026, 3, 25, 12, tzinfo=UTC))
    # Naive UTC, like created_at.
    assert start == datetime(2026, 3, 22, 23, tzinfo=UTC).replace(tzinfo=None)  # Mon 00:00 CET
    assert end == datetime(2026, 3, 29, 22, tzinfo=UTC).replace(tzinfo=None)  # Mon 00:00 CEST


# --- cooking time and the critic loop -------------------------------------------

WEEK = [30, 45, 0, 60, 15, 120, 1440]


def test_week_time_is_saved_and_validated(client):
    token = _signup(client)["token"]
    saved = client.post(
        "/auth/me/preferences", headers=_auth(token), json={"weekTimeAvailability": WEEK}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["weekTimeAvailability"] == WEEK

    for bad in ([30] * 6, [30] * 8, [20] + [30] * 6, [1455] + [0] * 6, [-15] + [0] * 6):
        response = client.post(
            "/auth/me/preferences", headers=_auth(token), json={"weekTimeAvailability": bad}
        )
        assert response.status_code == 422, bad

    cleared = client.post(
        "/auth/me/preferences", headers=_auth(token), json={"weekTimeAvailability": None}
    )
    assert cleared.json()["weekTimeAvailability"] is None


def _set_week(client, token, week):
    client.post("/auth/me/preferences", headers=_auth(token), json={"weekTimeAvailability": week})


def test_refine_sends_the_week_and_the_kept_recipes_to_the_critic(client, db, fake_planner):
    token = _signup(client)["token"]
    kept = _seed_plan(db)  # Pumpkin Gnocchi, 35 min
    _add_candidates(db, "Fresh Salad", "Spare Stew")
    client.post(f"/recipes/{kept}/meal-plan", headers=_auth(token))
    _set_week(client, token, [60] * 7)

    fake_planner.verdicts.append(
        Critique(passed=False, issues=["Two pumpkin dishes."], suggestions=["Add fish."])
    )
    response = client.post(
        "/generate/refine", headers=_auth(token), json={"mode": "replace", "note": "light"}
    )
    assert response.status_code == 200, response.text

    first = fake_planner.reviews[0]
    assert [r.name for r in first["plan"].recipes] == ["Pumpkin Gnocchi", "Fresh Salad"]
    assert first["fixed"] == frozenset({"Pumpkin Gnocchi"})
    assert first["user_pref"].week_time_availability == [60] * 7
    assert first["user_pref"].notes == "light"
    # The rejection went back to the planner for a second round, which passed.
    assert fake_planner[1]["feedback"].issues == ["Two pumpkin dishes."]
    assert len(fake_planner.reviews) == 2

    with db() as session:
        generation = session.query(Generation).filter_by(kind="refine").one()
        assert (generation.passed, generation.model) == (True, "agent+critic")


def test_the_weekly_plan_skips_recipes_longer_than_any_day(client, db, fake_planner):
    token = _signup(client)["token"]
    with db() as session:
        # Offers to plan from, but no plan yet this week.
        branch = Address(market_id="1", offers=[
            Offer(title="Kürbis", price=1.0, valid_till=datetime.now(STORE_TZ).date()),
        ])
        session.add(Supermarket(name="EDEKA", addresses=[branch]))
        _set_home(session.query(User).one(), branch)
        session.add_all([
            RecipeCache(name="Slow roast", servings=4, total_time=180),
            RecipeCache(name="Quick soup", servings=2, total_time=25),
        ])
        session.commit()
    _set_week(client, token, [30, 30, 0, 45, 0, 0, 0])

    response = client.post("/generate", headers=_auth(token))
    assert response.status_code == 200, response.text
    assert [r.name for r in fake_planner[0]["recipes"]] == ["Quick soup"]
    # The weekly plan is the agent's, and the critic reviews it.
    assert [r.name for r in fake_planner.reviews[0]["plan"].recipes] == ["Quick soup"]
    with db() as session:
        assert session.query(Generation).one().model == "agent+critic"


def test_a_tick_on_a_regular_price_item_is_saved_and_survives_a_refine(client, db, fake_planner):
    token = _signup(client)["token"]
    kept = _seed_plan(db)
    _add_candidates(db, "Dropped Soup", to_current_plan=True)
    _add_candidates(db, "Fresh Salad")
    client.post(f"/recipes/{kept}/meal-plan", headers=_auth(token))

    carrot = next(i for i in client.get("/shopping", headers=_auth(token)).json() if i["name"] == "carrot")
    ticked = client.patch(f"/shopping/{carrot['id']}", headers=_auth(token), json={"checked": True})
    assert ticked.status_code == 200 and ticked.json()["checked"] is True

    assert client.post("/generate/refine", headers=_auth(token), json={"mode": "replace"}).status_code == 200
    after = {i["name"]: i["checked"] for i in client.get("/shopping", headers=_auth(token)).json()}
    assert after["carrot"] is True
    assert "salt" not in after  # pantry never reaches the list


# --- home markets ----------------------------------------------------------------------

EDEKA_SEARCH = {"markets": [{
    "id": 10001604, "name": "EDEKA Frank",
    "contact": {"address": {"street": "Erlachstraße 45", "city": {"name": "Flein", "zipCode": "74223"}}},
}]}


class _Response:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


def test_market_search_finds_and_remembers_branches(client, db, monkeypatch):
    from cheaprecipe.ingestion import markets

    asked = []

    def fake_get(url, params, timeout):
        asked.append(params["path"])
        return _Response(EDEKA_SEARCH)

    monkeypatch.setattr(markets.requests, "get", fake_get)
    token = _signup(client)["token"]

    found = client.get("/markets", headers=_auth(token), params={"q": "Flein"}).json()
    assert "searchstring=Flein" in asked[0]
    assert [(m["chain"], m["name"], m["postalCode"]) for m in found] == [("edeka", "EDEKA Frank", "74223")]
    # Found once, the same row after: its id is what the profile stores.
    again = client.get("/markets", headers=_auth(token), params={"q": "Flein"}).json()
    assert again[0]["id"] == found[0]["id"]

    # ALDI SÜD has one national offer list, so one entry, found by name.
    aldi = client.get("/markets", headers=_auth(token), params={"q": "ald"}).json()
    assert aldi[0]["chain"] == "aldi" and aldi[0]["name"] == "ALDI SÜD"

    assert client.get("/markets", headers=_auth(token), params={"q": "F"}).status_code == 422


def test_market_search_falls_back_to_known_branches(client, db):
    # conftest keeps the network out of reach: EDEKA's search fails.
    with db() as session:
        session.add(Address(supermarket=Supermarket(name="EDEKA"), market_id="7", name="EDEKA Frank", city="Flein"))
        session.commit()
    token = _signup(client)["token"]
    found = client.get("/markets", headers=_auth(token), params={"q": "flein"}).json()
    assert [m["name"] for m in found] == ["EDEKA Frank"]


def test_planning_needs_a_home_market(client, db):
    token = _signup(client)["token"]
    response = client.post("/generate", headers=_auth(token))
    assert response.status_code == 409
    assert "home supermarket" in response.json()["detail"]


def test_offers_come_from_every_home_market_and_no_other(client, db, fake_planner):
    token = _signup(client)["token"]
    today = datetime.now(STORE_TZ).date()
    with db() as session:
        mine = [Address(market_id=str(n), offers=[Offer(title=f"Offer {n}", price=1.0, valid_till=today,
                                               quantity_amount=1, quantity_unit="kg",
                                               price_per_unit=1.0, price_per_unit_unit="kg")])
                for n in (1, 2)]
        other = Address(market_id="3", offers=[Offer(title="Elsewhere", price=1.0, valid_till=today)])
        session.add(Supermarket(name="EDEKA", addresses=[*mine, other]))
        session.add(RecipeCache(name="Quick soup", servings=2, total_time=25))
        _set_home(session.query(User).one(), *mine)
        session.commit()

    assert client.post("/generate", headers=_auth(token)).status_code == 200
    assert sorted(i.name for i in fake_planner[0]["offers"]) == ["Offer 1", "Offer 2"]


def test_a_new_home_market_without_offers_is_refreshed_in_the_background(client, db, monkeypatch):
    from app import scheduler

    ran = []
    monkeypatch.setattr(scheduler, "refresh_now", lambda factory, branches: ran.append(branches))
    token = _signup(client)["token"]
    with db() as session:
        branch = Address(supermarket=Supermarket(name="EDEKA"), market_id="42")
        session.add(branch)
        session.commit()
        branch_id = branch.id

    client.post("/auth/me/preferences", headers=_auth(token), json={"homeMarketIds": [branch_id]})
    assert ran == [[("edeka", "42")]]
    # Planning meanwhile says why there is nothing yet.
    response = client.post("/generate", headers=_auth(token))
    assert response.status_code == 409 and "being loaded" in response.json()["detail"]


# --- the week grid -----------------------------------------------------------------------

def test_meal_types_are_saved_in_the_days_order(client):
    token = _signup(client)["token"]
    saved = client.post("/auth/me/preferences", headers=_auth(token),
                        json={"mealTypes": ["dinner", "breakfast", "dinner"]})
    assert saved.status_code == 200 and saved.json()["mealTypes"] == ["breakfast", "dinner"]
    for bad in ([], ["brunch"]):
        rejected = client.post("/auth/me/preferences", headers=_auth(token), json={"mealTypes": bad})
        assert rejected.status_code == 422, bad


def test_the_week_grid_shows_the_meal_plan(client, db):
    token = _signup(client)["token"]
    gnocchi = _seed_plan(db)  # serves 2
    client.post("/auth/me/preferences", headers=_auth(token), json={"mealTypes": ["lunch", "dinner"]})

    empty = client.get("/mealplan", headers=_auth(token)).json()
    assert len(empty["days"]) == 5 and empty["emptyMeals"] == 10  # nothing in the plan yet

    client.post(f"/recipes/{gnocchi}/meal-plan", headers=_auth(token))
    week = client.get("/mealplan", headers=_auth(token)).json()
    monday, tuesday = week["days"][:2]
    assert monday["day"] == "monday" and [m["meal"] for m in monday["meals"]] == ["lunch", "dinner"]
    # Serves 2 for one person: cooked for Monday's dinner, Tuesday's lunch is leftovers.
    assert monday["meals"][1] == {"meal": "dinner", "recipeId": str(gnocchi),
                                  "title": "Pumpkin Gnocchi", "leftover": False}
    assert tuesday["meals"][0]["title"] == "Pumpkin Gnocchi" and tuesday["meals"][0]["leftover"]
    assert week["emptyMeals"] == 8 and week["spare"] == []


def test_a_recipe_without_its_method_gets_it_when_shown(client, db, monkeypatch):
    from cheaprecipe.matching import retrieval

    token = _signup(client)["token"]
    gnocchi = _seed_plan(db)
    with db() as session:
        row = session.get(RecipeCache, gnocchi)
        row.instructions, row.source, row.external_id = None, "spoonacular", "716429"
        session.commit()
    asked = []

    def information_bulk(ids, api_key=None):
        asked.append(list(ids))
        return [{"id": 716429, "analyzedInstructions": [{"steps": [
            {"number": 1, "step": "Roast the pumpkin."}, {"number": 2, "step": "Brown the butter."},
        ]}]}]

    monkeypatch.setattr(retrieval, "information_bulk", information_bulk)
    assert client.get("/recipes", headers=_auth(token)).json()[0]["steps"] == [
        "Roast the pumpkin.", "Brown the butter.",
    ]
    # Stored: the next view asks Spoonacular nothing.
    client.get(f"/recipes/{gnocchi}", headers=_auth(token))
    assert asked == [["716429"]]


def test_a_failed_method_fetch_still_shows_the_recipe(client, db):
    token = _signup(client)["token"]
    gnocchi = _seed_plan(db)
    with db() as session:
        row = session.get(RecipeCache, gnocchi)
        row.instructions, row.source, row.external_id = None, "spoonacular", "716429"
        session.commit()
    # conftest refuses the network: the fetch fails, the recipe is served.
    response = client.get(f"/recipes/{gnocchi}", headers=_auth(token))
    assert response.status_code == 200 and response.json()["steps"] == []
