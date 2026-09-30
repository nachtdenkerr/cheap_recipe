"""Response model for /mealplan — mirrors `WeekPlan` in types.ts."""

from datetime import date

from app.schemas import CamelModel
from cheaprecipe.vocabulary import MealType


class PlannedMeal(CamelModel):
    meal: MealType
    # None: nothing planned for this meal.
    recipe_id: str | None = None
    title: str | None = None
    # Cooked on an earlier day, eaten again.
    leftover: bool = False


class PlanDay(CamelModel):
    day: str
    date: date
    meals: list[PlannedMeal]


class SparePortions(CamelModel):
    recipe_id: str
    title: str
    portions: int


class WeekPlan(CamelModel):
    meal_types: list[MealType]
    household_size: int
    days: list[PlanDay]
    empty_meals: int
    # Portions the week has no meal for — for the weekend, or the freezer.
    spare: list[SparePortions]
