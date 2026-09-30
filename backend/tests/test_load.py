"""`cheaprecipe load`: pipeline files -> database. No network, in-memory SQLite."""

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cheaprecipe import pipeline
from cheaprecipe.db.load import LoadReport, load_files, load_offers
from cheaprecipe.db.models import (
    Address,
    CanonicalIngredient,
    Offer,
    RecipeCache,
    RecipeIngredient,
    Supermarket,
)
from cheaprecipe.db.session import init_db, make_engine

FIXTURES = Path(__file__).parent / "fixtures"
OFFERS = FIXTURES / "edeka_offers_sample.csv"
RECIPES = FIXTURES / "edeka_recipes_sample.json"


@pytest.fixture
def session():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        yield session


def _count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


def _recipe(session, title) -> RecipeCache:
    return session.scalars(select(RecipeCache).where(RecipeCache.name == title)).one()


def _line(recipe: RecipeCache, name: str) -> RecipeIngredient:
    return next(line for line in recipe.ingredients if line.name == name)


def test_offers_and_recipes_are_loaded(session):
    report = load_files(session, OFFERS, RECIPES, "edeka", "10001604")

    # 8 cookable offers; the cat litter is not for cooking.
    assert (report.offers_added, report.offers_skipped) == (8, 1)
    assert _count(session, Offer) == 8
    branch = session.scalars(select(Address)).one()
    assert (branch.market_id, branch.supermarket.name) == ("10001604", "EDEKA")

    # The dessert and the all-"1 serving" recipe are not plannable meals.
    assert (report.recipes_added, report.recipes_skipped) == (4, 2)
    assert {r.name for r in session.scalars(select(RecipeCache))} == {
        "Chicken Tomato Pasta", "Sausage and Apple Bake", "Buttered Onion Pasta", "Plain Rice",
    }


def test_recipe_fields_come_through(session):
    load_files(session, OFFERS, RECIPES, "edeka", "10001604")
    pasta = _recipe(session, "Chicken Tomato Pasta")

    assert (pasta.source, pasta.external_id, pasta.servings) == ("spoonacular", "1001", 2)
    assert (pasta.cooking_time, pasta.total_time) == (20, 30)  # 10 prep + 20 cooking
    assert pasta.cuisine.name == "Italian"
    assert pasta.instructions.splitlines()[0] == "Boil the pasta."
    # Spoonacular units become ours: spoons to litres, counts to pieces.
    oil = _line(pasta, "olive oil")
    assert (oil.amount, oil.unit) == (pytest.approx(0.03), "l")
    assert _line(pasta, "onion").unit == "Stück"


def test_recipe_lines_share_the_canonical_id_of_the_offer_they_match(session):
    load_files(session, OFFERS, RECIPES, "edeka", "10001604")
    offers = {o.ingredient_en: o for o in session.scalars(select(Offer))}
    pasta = _recipe(session, "Chicken Tomato Pasta")
    bake = _recipe(session, "Sausage and Apple Bake")

    # Same matcher as the planner: "chicken breast" is the fillets on offer,
    # "sausages" the cheese sausage, "onions" the 2 kg bag.
    assert _line(pasta, "chicken breast").canonical_ingredient_id == (
        offers["fresh chicken breast fillets"].canonical_ingredient_id
    )
    assert _line(bake, "sausages").canonical_ingredient is offers["cheese sausage"].canonical_ingredient
    assert _line(bake, "onions").canonical_ingredient is offers["onion"].canonical_ingredient

    # A line with no offer gets a canonical ingredient of its own.
    parsley = _line(pasta, "parsley").canonical_ingredient
    assert parsley.name == "parsley"
    assert parsley.id not in {o.canonical_ingredient_id for o in offers.values()}


def test_loading_again_updates_instead_of_duplicating(session):
    load_files(session, OFFERS, RECIPES, "edeka", "10001604")
    counts = {m: _count(session, m) for m in (Offer, RecipeCache, RecipeIngredient, CanonicalIngredient, Supermarket, Address)}

    report = load_files(session, OFFERS, RECIPES, "edeka", "10001604")

    assert (report.offers_added, report.offers_updated) == (0, 8)
    assert (report.recipes_added, report.recipes_updated) == (0, 4)
    assert {m: _count(session, m) for m in counts} == counts


def test_a_changed_price_is_updated(session):
    frame = pd.read_csv(OFFERS)
    load_offers(session, frame, "edeka", "10001604")
    frame.loc[frame.ingredient_en == "onion", "price"] = 0.99
    load_offers(session, frame, "edeka", "10001604")

    onion = session.scalars(select(Offer).where(Offer.ingredient_en == "onion")).one()
    assert onion.price == 0.99


def test_the_cli_writes_to_the_database_it_is_given(tmp_path):
    url = f"sqlite:///{tmp_path / 'cheaprecipe.db'}"
    pipeline.load(offers_path=OFFERS, recipes_path=RECIPES, database_url=url)

    engine = make_engine(url)
    with Session(engine) as session:
        assert _count(session, Offer) == 8
        assert _count(session, RecipeCache) == 4
    # The file persists: a second process reads the same rows.
    assert (tmp_path / "cheaprecipe.db").stat().st_size > 0


def test_offers_alone_load_without_recipes(session, tmp_path):
    report = load_files(session, OFFERS, tmp_path / "missing.json", "edeka", "10001604")
    assert report.offers_added == 8 and report.recipes_added == 0


def test_fixture_recipes_parse_like_the_pipeline_output():
    # Guard: the fixture keeps the Spoonacular shape the loader reads.
    recipes = json.loads(RECIPES.read_text())
    assert all({"id", "title", "extendedIngredients", "dishTypes"} <= r.keys() for r in recipes)


def test_diet_and_allergens_are_stored(session):
    load_files(session, OFFERS, RECIPES, "edeka", "10001604")
    diets = {r.name: r.diet_type for r in session.scalars(select(RecipeCache))}
    # The sausage bake is flagged vegetarian in the fixture — wrongly; the sausages win.
    assert diets == {
        "Chicken Tomato Pasta": "normal",
        "Sausage and Apple Bake": "normal",
        "Buttered Onion Pasta": "vegetarian",
        "Plain Rice": "vegan",
    }
    butter = session.scalars(
        select(CanonicalIngredient).where(CanonicalIngredient.name == "unsalted butter")
    ).one()
    assert butter.allergens == ["milk"]


def test_undated_offers_get_the_week_they_were_fetched_in(session):
    # ALDI SÜD's weekly-offers page has no dates: validTill is NaT, no validFrom.
    frame = pd.read_csv(OFFERS).drop(columns=["validFrom"])
    frame["validTill"] = pd.NaT
    wednesday = date(2026, 9, 30)
    load_offers(session, frame, "aldi", "1588161426582123", fetched_on=wednesday)

    weeks = {(o.valid_from, o.valid_till) for o in session.scalars(select(Offer))}
    assert weeks == {(date(2026, 9, 28), date(2026, 10, 3))}  # Monday to Saturday
    # Loading the same week again updates instead of duplicating.
    report = LoadReport()
    load_offers(session, frame, "aldi", "1588161426582123", report, fetched_on=wednesday)
    assert report.offers_added == 0 and report.offers_updated == 8


def test_the_course_comes_from_spoonacular_dish_types():
    from cheaprecipe.matching.index import course_of

    assert course_of({"dishTypes": ["morning meal", "brunch", "breakfast"]}) == "breakfast"
    assert course_of({"dishTypes": ["lunch", "main course", "dinner"]}) == "main"
    assert course_of({"dishTypes": ["brunch", "main course"]}) == "main"
    assert course_of({"dishTypes": []}) is None


def test_pooled_recipes_are_relinked_to_new_offers_by_their_base_name(session):
    load_files(session, OFFERS, RECIPES, "edeka", "10001604")
    pasta = _recipe(session, "Chicken Tomato Pasta")
    parsley = _line(pasta, "parsley")
    assert parsley.canonical_ingredient.name == "parsley"  # nothing on offer covers it

    # Next week a herb bunch is on offer, known to recipes as parsley.
    frame = pd.DataFrame([{
        "title": "Kräuterbund", "price": 0.99, "ingredient_en": "herb bunch", "base_ingredient": "parsley",
        "meal_role": "vegetable", "can_cook": True, "quantity_amount": 1, "quantity_unit": "Stück",
        "quantity_basis": "package", "price_per_unit": 0.99, "price_per_unit_unit": "Stück",
    }])
    [herbs] = load_offers(session, frame, "edeka", "10001604")
    from cheaprecipe.db.load import relink_recipes
    assert relink_recipes(session, [herbs]) >= 1
    assert parsley.canonical_ingredient is herbs.canonical_ingredient
    assert herbs.meal_role == "vegetable" and herbs.base_ingredient == "parsley"
