"""The week grid: which recipe in the meal plan is eaten at which meal.

Computed, not stored: calculation/schedule.py places the recipes the user
added to their meal plan into Monday to Friday, by course, spreading each
cooking over servings ÷ household meals. It changes as they add or remove
recipes, as the shopping list does.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter

from app.deps import CurrentUser, SessionDep
from app.presenters import latest_generation
from app.schemas.mealplan import PlanDay, PlannedMeal, SparePortions, WeekPlan
from cheaprecipe.calculation.schedule import WEEKDAYS, build_week
from cheaprecipe.db.adapters import STORE_TZ, recipe_candidate
from cheaprecipe.vocabulary import DEFAULT_MEAL_TYPES

router = APIRouter(prefix="/mealplan", tags=["mealplan"])


@router.get("")
def week_plan(user: CurrentUser, session: SessionDep) -> WeekPlan:
    pref = user.preference
    household = (pref.household_size if pref else None) or 1
    meal_types = list((pref.meal_types if pref else None) or DEFAULT_MEAL_TYPES)
    generation = latest_generation(session, user)
    # In the order they were suggested, which is the planner's order.
    planned = [r for r in generation.recipes if r in generation.planned_recipes] if generation else []
    ids = {row.name: str(row.id) for row in planned}
    week = build_week([recipe_candidate(row, set()) for row in planned], household, meal_types)

    today = datetime.now(STORE_TZ).date()
    monday = today - timedelta(days=today.weekday())
    days = [
        PlanDay(
            day=day,
            date=monday + timedelta(days=index),
            meals=[
                PlannedMeal(
                    meal=slot.meal, recipe_id=ids.get(slot.recipe) if slot.recipe else None,
                    title=slot.recipe, leftover=slot.leftover,
                )
                for slot in week.slots if slot.day == day
            ],
        )
        for index, day in enumerate(WEEKDAYS)
    ]
    return WeekPlan(
        meal_types=meal_types,
        household_size=household,
        days=days,
        empty_meals=week.empty_slots,
        spare=[
            SparePortions(recipe_id=ids[name], title=name, portions=n)
            for name, n in week.spare_portions.items()
        ],
    )
