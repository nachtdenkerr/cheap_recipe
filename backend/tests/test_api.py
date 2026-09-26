"""API endpoints against an in-memory database — no network, no API key."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import security
from app.main import app
from app.quota import STORE_TZ, week_bounds
from cheaprecipe.agents import planner
from cheaprecipe.agents.contracts import Plan
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
            name="Pumpkin Gnocchi", servings=2, total_time=35,
            instructions="Roast the pumpkin.\n\nBrown the butter.",
            ingredients=[
                RecipeIngredient(name="pumpkin", amount=500, unit="g", canonical_ingredient=pumpkin),
                RecipeIngredient(name="butter", amount=50, unit="g", canonical_ingredient=butter),
                RecipeIngredient(name="sage", amount=8, unit="leaves"),
            ],
        )
        user = session.query(User).filter_by(email=email).one()
        generation = Generation(
            user=user, diet_type="vegetarian", recipes=[recipe],
            items=[
                GenerationItem(offer=pumpkin_offer, amount=500, unit="g"),
                GenerationItem(offer=butter_offer, amount=50, unit="g"),
                GenerationItem(name="sage", amount=8, unit="leaves"),
            ],
        )
        session.add_all([edeka, generation])
        session.commit()
        return recipe.id


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
        "market": None, "cuisines": [], "whiteList": [], "blackList": [],
        "healthGoal": None, "age": None, "gender": None,
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
        session.add(Supermarket(name="EDEKA"))
        session.commit()

    response = client.post(
        "/auth/me/preferences",
        headers=_auth(token),
        json={"dietType": "vegan", "householdSize": 2, "allergens": ["nuts"],
              "market": "edeka", "cuisines": ["Italian"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["dietType"], body["householdSize"], body["market"]) == ("vegan", 2, "EDEKA")
    assert body["allergens"] == ["nuts"] and body["cuisines"] == ["Italian"]

    for bad in ({"dietType": "ketogenic"}, {"allergens": ["pollen"]}):
        rejected = client.post("/auth/me/preferences", headers=_auth(token), json=bad)
        assert rejected.status_code == 422, bad

    unknown = client.post("/auth/me/preferences", headers=_auth(token), json={"market": "Nowhere"})
    assert unknown.status_code == 422


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

    pumpkin, _butter, sage = recipe["ingredients"]
    assert pumpkin["offer"]["priceCents"] == 111 and not pumpkin["pantry"]
    assert sage == {"name": "sage", "amount": "8 leaves", "offer": None, "pantry": True}

    # Half the pumpkin (0.555) + a fifth of the butter (0.358).
    assert recipe["cost"]["totalCents"] == 91
    assert recipe["cost"]["perServingCents"] == 46
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
    assert len(client.get("/shopping", headers=_auth(token)).json()) == 2

    client.delete(f"/recipes/{recipe_id}/meal-plan", headers=_auth(token))
    assert client.get("/shopping", headers=_auth(token)).json() == []


def test_shopping_list_and_ticking_items(client, db):
    token = _signup(client)["token"]
    recipe_id = _seed_plan(db)
    client.post(f"/recipes/{recipe_id}/meal-plan", headers=_auth(token))

    items = client.get("/shopping", headers=_auth(token)).json()
    # The sage line has no offer, so there is nothing to buy on the list.
    assert [i["offer"]["title"] for i in items] == ["Hokkaido Kürbis", "Weihenstephan Butter"]
    assert all(i["quantity"] == 1 and i["usedBy"] == ["Pumpkin Gnocchi"] for i in items)

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


@pytest.fixture
def fake_planner(monkeypatch):
    """Stand-in for the stubbed planner: takes the first N candidates, records calls."""
    calls = []

    def fake_plan(recipes, offers, number_of_meals, **kwargs):
        calls.append({"recipes": recipes, "offers": offers, "n": number_of_meals, **kwargs})
        return Plan(recipes=recipes[:number_of_meals], grocery_list=[], total_cost=0.0)

    monkeypatch.setattr(planner, "plan", fake_plan)
    monkeypatch.setattr(planner, "plan_with_agent", fake_plan)
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
    assert [(i["offer"]["title"], i["checked"]) for i in items] == [
        ("Hokkaido Kürbis", False), ("Weihenstephan Butter", True),
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
    _add_candidates(db, "Mild Curry")
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


def test_failed_refine_does_not_use_the_quota(client, db):
    token = _signup(client)["token"]
    _seed_plan(db)
    _add_candidates(db, "Anything")
    # The real planner is still stubbed, so this fails on our side.
    response = client.post("/generate/refine", headers=_auth(token), json={"mode": "replace"})
    assert response.status_code == 501
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
