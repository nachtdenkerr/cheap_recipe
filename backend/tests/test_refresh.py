"""The weekly refresh, its scheduler, and the on-demand top-up — all offline.

Spoonacular and the offers pipeline are stand-ins: the pipeline returns the
fixture offers (moved to this week), Spoonacular the fixture recipes plus
whatever a test adds, and records what it was asked.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import scheduler
from cheaprecipe import refresh
from cheaprecipe.db.adapters import STORE_TZ
from cheaprecipe.db.models import (
    Address,
    Offer,
    RecipeFetch,
    Supermarket,
    User,
    UserPreference,
    WeeklyRefresh,
)
from cheaprecipe.db.session import init_db, make_engine
from cheaprecipe.matching import retrieval

FIXTURES = Path(__file__).parent / "fixtures"


def _this_weeks_offers() -> pd.DataFrame:
    frame = pd.read_csv(FIXTURES / "edeka_offers_sample.csv")
    monday = refresh.week_start()
    frame["validFrom"] = monday.isoformat()
    frame["validTill"] = (monday + timedelta(days=6)).isoformat()
    return frame


def _meal(recipe_id, title, lines, vegetarian=False):
    """A Spoonacular-shaped meal; `lines` are (name, grams)."""
    return {
        "id": recipe_id, "title": title, "servings": 2, "readyInMinutes": 25,
        "cuisines": [], "dishTypes": ["main course"], "diets": [],
        "vegetarian": vegetarian, "vegan": False,
        "extendedIngredients": [
            {"name": name, "aisle": "", "measures": {"metric": {"amount": grams, "unitShort": "g"}}}
            for name, grams in lines
        ],
        "analyzedInstructions": [],
    }


VEGGIE_MEALS = [
    _meal(2001, "Tomato Butter Pasta", [("pasta", 200), ("cherry tomatoes", 250), ("butter", 30), ("onion", 100)], True),
    _meal(2002, "Onion Tart", [("onion", 400), ("butter", 80), ("apple", 150)], True),
]


class FakeSpoonacular:
    def __init__(self):
        self.calls = []
        self.results = json.loads((FIXTURES / "edeka_recipes_sample.json").read_text()) + VEGGIE_MEALS

    def __call__(self, ingredients, **kwargs):
        self.calls.append(kwargs)
        diet = kwargs.get("diet")
        found = [r for r in self.results if diet != "vegetarian" or r.get("vegetarian")]
        offset, number = kwargs.get("offset", 0), kwargs.get("number", 40)
        return found[offset : offset + number]


@pytest.fixture
def factory():
    engine = make_engine("sqlite://", poolclass=StaticPool)
    init_db(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def spoonacular(monkeypatch):
    fake = FakeSpoonacular()
    monkeypatch.setattr(retrieval, "complex_search", fake)
    return fake


@pytest.fixture
def pipeline_runs(monkeypatch):
    from cheaprecipe import pipeline

    runs = []

    def build_offers(store, store_id):
        runs.append(store)
        return _this_weeks_offers()

    monkeypatch.setattr(pipeline, "build_offers", build_offers)
    return runs


def _vegetarian_user(session):
    user = User(username="veg", email="veg@example.test", password_hash="x",
                preference=UserPreference(diet_type="vegetarian"))
    session.add(user)
    session.commit()
    return user


# --- the refresh ------------------------------------------------------------------------

def test_weekly_refresh_loads_offers_once_and_fills_every_diet(factory, spoonacular, pipeline_runs):
    with factory() as session:
        _vegetarian_user(session)
        summary = refresh.weekly_refresh(session, "edeka")

        assert pipeline_runs == ["edeka"]
        assert session.scalar(select(func.count()).select_from(Offer)) == 8
        # One search per diet in use: "normal" (everyone else) and "vegetarian".
        assert sorted(call["diet"] or "normal" for call in spoonacular.calls) == ["normal", "vegetarian"]
        assert set(summary.pools) == {"normal", "vegetarian"}
        assert session.scalar(select(func.count()).select_from(RecipeFetch)) == 2

        # Again the same week: the offers are current, so the pipeline is not run.
        refresh.weekly_refresh(session, "edeka")
        assert pipeline_runs == ["edeka"]


def test_a_full_pool_is_not_fetched_again(factory, spoonacular, pipeline_runs):
    with factory() as session:
        refresh.refresh_offers(session, "edeka")
        first = refresh.ensure_pool(session, "edeka", refresh.PoolFilter(), minimum=1)
        assert first.fetched
        second = refresh.ensure_pool(session, "edeka", refresh.PoolFilter(), minimum=1)
        assert not second.fetched and "usable already" in second.skipped_reason


def test_asking_again_pages_past_what_was_returned(factory, spoonacular, pipeline_runs):
    with factory() as session:
        refresh.refresh_offers(session, "edeka")
        wanted = refresh.PoolFilter(diet="vegetarian")
        refresh.ensure_pool(session, "edeka", wanted, minimum=100)
        refresh.ensure_pool(session, "edeka", wanted, minimum=100)
        first, second = spoonacular.calls
        assert second["offset"] == first["offset"] + len(
            [r for r in spoonacular.results if r.get("vegetarian")]
        )


def test_the_caps_protect_the_quota(factory, spoonacular, pipeline_runs, monkeypatch):
    monkeypatch.setattr(refresh, "MAX_FETCHES_PER_QUERY", 2)
    with factory() as session:
        refresh.refresh_offers(session, "edeka")
        wanted = refresh.PoolFilter(diet="vegetarian")
        results = [refresh.ensure_pool(session, "edeka", wanted, minimum=100) for _ in range(3)]
        assert [r.fetched for r in results] == [True, True, False]
        assert "already this week" in results[2].skipped_reason
        assert len(spoonacular.calls) == 2


def test_allergens_and_dislikes_are_passed_to_spoonacular(factory, spoonacular, pipeline_runs):
    with factory() as session:
        refresh.refresh_offers(session, "edeka")
        wanted = refresh.PoolFilter(diet="vegetarian", allergens=frozenset({"milk", "celery"}), dislikes=("apple",))
        refresh.ensure_pool(session, "edeka", wanted, minimum=100)
        call = spoonacular.calls[0]
        # Celery has no Spoonacular intolerance: it is filtered locally only.
        assert (call["diet"], call["intolerances"], call["exclude_ingredients"]) == ("vegetarian", ["dairy"], ["apple"])


def test_a_failed_search_is_not_an_error(factory, pipeline_runs, monkeypatch):
    def quota_spent(*args, **kwargs):
        raise RuntimeError("Spoonacular refused the request (HTTP 402)")

    monkeypatch.setattr(retrieval, "complex_search", quota_spent)
    with factory() as session:
        refresh.refresh_offers(session, "edeka")
        result = refresh.ensure_pool(session, "edeka", refresh.PoolFilter())
        assert not result.fetched and "402" in result.skipped_reason


# --- the scheduler ---------------------------------------------------------------------

def _monday(hour: int) -> datetime:
    return datetime.combine(refresh.week_start(), datetime.min.time(), tzinfo=STORE_TZ) + timedelta(hours=hour)


@pytest.fixture
def fake_refresh(monkeypatch):
    runs = []

    def weekly_refresh(session, store, store_id):
        runs.append(f"{store}:{store_id}")
        return refresh.RefreshSummary(offers="fake", pools={"normal": "fake"})

    monkeypatch.setattr(scheduler, "weekly_refresh", weekly_refresh)
    monkeypatch.setenv("WEEKLY_REFRESH", "on")
    monkeypatch.setenv("REFRESH_HOUR", "5")
    return runs


BRANCH = "edeka:10001604"


@pytest.fixture
def home_market(factory):
    """A user with EDEKA Frank as home market: the branch the scheduler covers."""
    with factory() as session:
        branch = Address(supermarket=Supermarket(name="EDEKA"), market_id="10001604", name="EDEKA Frank")
        session.add(User(username="u", email="u@example.test", password_hash="x",
                         preference=UserPreference(home_markets=[branch])))
        session.commit()
    return branch


def test_nothing_to_do_without_home_markets(factory, fake_refresh):
    assert scheduler.run_due(factory, _monday(6)) == []


def test_every_home_market_in_use_is_refreshed(factory, fake_refresh, home_market):
    with factory() as session:
        aldi = Address(supermarket=Supermarket(name="ALDI SÜD"), market_id="1588161426582123")
        session.add(User(username="v", email="v@example.test", password_hash="x",
                         preference=UserPreference(home_markets=[aldi, session.get(Address, home_market.id)])))
        session.commit()
    assert sorted(scheduler.run_due(factory, _monday(6))) == ["aldi:1588161426582123", BRANCH]


def test_a_new_home_market_is_refreshed_now_not_on_monday(factory, fake_refresh):
    # Wednesday, before any due check: refresh_now ignores the schedule, once.
    assert scheduler.refresh_now(factory, [("edeka", "123")]) == ["edeka:123"]
    assert scheduler.refresh_now(factory, [("edeka", "123")]) == []


def test_not_before_monday_morning(factory, fake_refresh, home_market):
    assert scheduler.run_due(factory, _monday(4)) == []
    assert fake_refresh == []


def test_once_a_week_after_monday_morning(factory, fake_refresh, home_market):
    assert scheduler.run_due(factory, _monday(6)) == [BRANCH]
    assert scheduler.run_due(factory, _monday(7)) == []  # done this week
    # Catching up later in the week works too — but only once.
    assert scheduler.run_due(factory, _monday(24 * 3)) == []
    assert fake_refresh == [BRANCH]
    with factory() as session:
        row = session.scalars(select(WeeklyRefresh)).one()
        assert (row.status, row.summary["offers"]) == ("done", "fake")


def test_a_failed_run_is_retried_later(factory, fake_refresh, home_market, monkeypatch):
    def broken(session, store, store_id):
        raise RuntimeError("EDEKA is down")

    monkeypatch.setattr(scheduler, "weekly_refresh", broken)
    assert scheduler.run_due(factory, _monday(6)) == [BRANCH]
    with factory() as session:
        row = session.scalars(select(WeeklyRefresh)).one()
        assert (row.status, row.attempts) == ("failed", 1) and "EDEKA is down" in row.error

    # Too soon to retry; an hour and more later it is retried.
    real_now = datetime.now(STORE_TZ)
    assert scheduler.run_due(factory, real_now) == []
    assert scheduler.run_due(factory, real_now + scheduler.RETRY_AFTER + timedelta(minutes=1)) == [BRANCH]


def test_a_stale_running_row_is_taken_over(factory, fake_refresh, home_market):
    with factory() as session:
        session.add(WeeklyRefresh(
            store=BRANCH, week_start=refresh.week_start(), status="running",
            started_at=(_monday(6) - scheduler.STALE_AFTER - timedelta(minutes=5)).replace(tzinfo=None),
        ))
        session.commit()
    assert scheduler.run_due(factory, _monday(6)) == [BRANCH]


def test_switched_off(factory, fake_refresh, home_market, monkeypatch):
    monkeypatch.setenv("WEEKLY_REFRESH", "off")
    assert scheduler.run_due(factory, _monday(6)) == []


def test_a_breakfast_pool_is_searched_as_breakfast(factory, spoonacular, pipeline_runs):
    with factory() as session:
        refresh.refresh_offers(session, "edeka")
        refresh.ensure_pool(session, "edeka", refresh.PoolFilter(course="breakfast"), minimum=100)
        refresh.ensure_pool(session, "edeka", refresh.PoolFilter(), minimum=100)
        breakfast, main = spoonacular.calls
        assert breakfast["dish_type"] == "breakfast" and main["dish_type"] == "main course"
        # Two different questions, each with its own page and cap.
        assert refresh.PoolFilter(course="breakfast").query_key() != refresh.PoolFilter().query_key()



def _offer(title, role, base, price, en=None):
    return Offer(title=title, ingredient_en=en or title, meal_role=role, base_ingredient=base,
                 price=price, can_cook=True)


ALDI_WEEK = [
    _offer("fruit gummies", "snack_or_sweet", None, 0.79),
    _offer("caramel protein pudding", "snack_or_sweet", None, 0.99),
    _offer("spring onions", "vegetable", "spring onion", 0.49),
    _offer("cauliflower", "vegetable", "cauliflower", 1.49),
    _offer("potato pockets with emmental cheese", "convenience", None, 2.49),
    _offer("marinated pork neck steak", "protein", "pork shoulder", 3.59),
    _offer("marinated chicken steaks", "protein", "chicken breast", 4.99),
    _offer("seafood prawns", "protein", "shrimp", 5.99),
    _offer("eggs", "protein", "eggs", 1.99),
    _offer("greek yogurt", "dairy", "yogurt", 0.99),
]


def test_a_main_is_searched_per_protein_by_its_recipe_name():
    labels = [label for label, _ in refresh.searches(ALDI_WEEK, refresh.PoolFilter())]
    # Cheapest protein first; no gummies, pudding or potato pockets anywhere.
    assert labels == ["eggs", "pork shoulder", "chicken breast", "shrimp"]
    assert refresh.searches(ALDI_WEEK, refresh.PoolFilter())[1] == ("pork shoulder", ["pork shoulder"])


def test_a_vegetarian_is_not_searched_meat():
    labels = [label for label, _ in refresh.searches(ALDI_WEEK, refresh.PoolFilter(diet="vegetarian"))]
    assert labels == ["eggs"]
    vegan = refresh.searches(ALDI_WEEK, refresh.PoolFilter(diet="vegan"))
    assert vegan == [("vegetables", ["spring onion", "cauliflower"])]


def test_a_breakfast_is_searched_by_what_breakfasts_are_made_of():
    [(label, names)] = refresh.searches(ALDI_WEEK, refresh.PoolFilter(course="breakfast"))
    assert label == "breakfast" and names == ["yogurt", "eggs"]


def test_offers_without_meal_roles_are_searched_as_before():
    old = [Offer(title="a", ingredient_en="onion", price=1.0), Offer(title="b", ingredient_en="butter", price=0.5)]
    assert refresh.searches(old, refresh.PoolFilter()) == [("offers", ["butter", "onion"])]


def test_a_top_up_stops_searching_once_the_pool_is_big_enough(factory, spoonacular, pipeline_runs, monkeypatch):
    with factory() as session:
        refresh.refresh_offers(session, "edeka")
        offers = list(session.scalars(select(Offer)))
        for offer, (role, base) in zip(offers, [("protein", "chicken breast"), ("protein", "pork shoulder"),
                                                 ("protein", "shrimp")]):
            offer.meal_role, offer.base_ingredient = role, base
        session.commit()
        result = refresh.fetch_recipes(session, "edeka", offers, refresh.PoolFilter(), "top-up", minimum=1)
        # The first search already made the pool big enough: one search, not three.
        assert result.fetched and len(spoonacular.calls) == 1
