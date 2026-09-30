"""The week grid (calculation/schedule.py) and the course quotas — no model."""

from cheaprecipe.agents import planner
from cheaprecipe.agents.contracts import Ingredient, Quantity, Recipe
from cheaprecipe.calculation.schedule import build_week, portions


def recipe(name, servings, course="main"):
    return Recipe(
        name=name, servings=servings, cooking_time=20, cuisine=[], course=course,
        ingredients=[Ingredient(name="onion", quantity=Quantity(amount=100, unit="g"))],
    )


def grid(week):
    return {(s.day, s.meal): (s.recipe, s.leftover) for s in week.slots}


def test_a_cooking_feeds_the_household_over_the_next_days():
    # Serves 4, two people: cooked Monday, eaten again Tuesday.
    week = build_week([recipe("Stew", 4)], household_size=2, meal_types=["dinner"])
    g = grid(week)
    assert g[("monday", "dinner")] == ("Stew", False)
    assert g[("tuesday", "dinner")] == ("Stew", True)
    assert g[("wednesday", "dinner")] == (None, False)
    assert week.empty_slots == 3


def test_never_twice_a_day_and_at_most_three_days():
    week = build_week([recipe("Curry", 8)], household_size=1, meal_types=["lunch", "dinner"])
    g = grid(week)
    days = [day for (day, meal), (name, _) in g.items() if name == "Curry"]
    assert days == ["monday", "tuesday", "wednesday"]  # one meal a day, three days
    assert week.spare_portions == {"Curry": 5}


def test_breakfasts_go_to_breakfast_and_mains_to_lunch_and_dinner():
    week = build_week(
        [recipe("Porridge", 2, "breakfast"), recipe("Pasta", 2), recipe("Soup", 2)],
        household_size=1, meal_types=["breakfast", "lunch", "dinner"],
    )
    g = grid(week)
    assert g[("monday", "breakfast")] == ("Porridge", False)
    assert g[("tuesday", "breakfast")] == ("Porridge", True)
    # Cooked at dinner, spread over the week; the leftovers are the next lunch.
    assert g[("monday", "dinner")] == ("Pasta", False) and g[("tuesday", "lunch")] == ("Pasta", True)
    assert g[("wednesday", "dinner")] == ("Soup", False) and g[("thursday", "lunch")] == ("Soup", True)
    assert len(week.slots) == 15  # Monday to Friday, three meals


def test_meals_the_user_does_not_plan_are_not_in_the_grid():
    week = build_week([recipe("Pasta", 2)], household_size=1, meal_types=["dinner"])
    assert {s.meal for s in week.slots} == {"dinner"}
    assert "Monday: dinner Pasta" in week.describe()


def test_portions_are_at_least_one():
    assert portions(recipe("Toast", 1), household_size=4) == 1


def test_course_quotas():
    assert planner.course_quotas(5, ["breakfast", "lunch", "dinner"]) == {"breakfast": 1, "main": 4}
    assert planner.course_quotas(5, ["lunch", "dinner"]) == {"main": 5}
    assert planner.course_quotas(3, ["breakfast"]) == {"breakfast": 3}


def test_the_greedy_week_keeps_to_the_courses(monkeypatch):
    monkeypatch.setattr(planner, "using_offers", lambda recipes, offers, minimum=3: list(recipes))
    candidates = [recipe("Pasta", 2), recipe("Soup", 2), recipe("Eggs", 2, "breakfast")]
    week = planner.plan(candidates, [], 2, courses={"breakfast": 1, "main": 1})
    assert sorted(course for course in (r.course for r in week.recipes)) == ["breakfast", "main"]
    # No breakfast among the candidates: the week is short, not filled with a main.
    week = planner.plan(candidates[:2], [], 2, courses={"breakfast": 1, "main": 1})
    assert len(week.recipes) == 1


def test_every_recipe_is_cooked_before_leftovers_take_the_slots():
    # Five mains serving 4 for one person would fill ten slots with the first
    # four alone; the fifth must still get its own.
    names = ["A", "B", "C", "D", "E"]
    week = build_week([recipe(n, 4) for n in names], household_size=1, meal_types=["lunch", "dinner"])
    cooked = {s.recipe: s.day for s in week.slots if s.recipe and not s.leftover}
    assert set(cooked) == set(names)
    # One cooking a day, at dinner; leftovers the next days' lunches.
    assert list(cooked.values()) == ["monday", "tuesday", "wednesday", "thursday", "friday"]
    assert week.empty_slots == 1  # Monday's lunch: nothing is cooked before it


def test_leftovers_stay_within_three_days_of_cooking():
    week = build_week([recipe("A", 8)], household_size=1, meal_types=["dinner"])
    # Serves 8: Monday, Tuesday, Wednesday — not the rest of the week.
    assert [s.day for s in week.slots if s.recipe == "A"] == ["monday", "tuesday", "wednesday"]
    assert week.spare_portions == {"A": 5}
