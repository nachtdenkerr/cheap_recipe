"""The week grid: which recipe is eaten at which meal, Monday to Friday.

Deterministic, like the rest of calculation/. A recipe cooked once feeds the
household `servings // household_size` times, so one cooking fills that many
slots: the first is the day it is cooked, the others are leftovers on the
following days (never twice on one day), within MAX_DAYS_PER_COOKING days of
cooking — what keeps in the fridge. Every recipe is cooked once before any
leftovers are placed, so each gets a slot while there are slots. Breakfast
recipes go to breakfast slots, the others to lunch and dinner; a slot
nothing covers stays empty.

The critic reviews the grid (agents/critic.py) — the same dish on too many
days, a week that is mostly empty — and the loop has the planner revise.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cheaprecipe.agents.contracts import Recipe
from cheaprecipe.vocabulary import MEAL_TYPES, MealType

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday")
MAX_DAYS_PER_COOKING = 3


@dataclass(frozen=True)
class Slot:
    day: str
    meal: MealType
    recipe: str | None = None
    # Cooked on an earlier day, eaten again here.
    leftover: bool = False


@dataclass
class Week:
    slots: list[Slot]
    # Portions a recipe makes that the grid has no slot for.
    spare_portions: dict[str, int] = field(default_factory=dict)

    @property
    def empty_slots(self) -> int:
        return sum(1 for slot in self.slots if slot.recipe is None)

    def describe(self) -> str:
        """The grid as text, one line per day — for the critic."""
        lines = []
        for day in WEEKDAYS:
            meals = [
                f"{s.meal} {s.recipe or '(nothing)'}" + (" (leftovers)" if s.leftover else "")
                for s in self.slots if s.day == day
            ]
            lines.append(f"{day.capitalize()}: " + "; ".join(meals))
        return "\n".join(lines)


def portions(recipe: Recipe, household_size: int) -> int:
    """How many meals one cooking gives the household — at least one."""
    return max(1, recipe.servings // max(1, household_size))


def build_week(
    recipes: list[Recipe], household_size: int = 1, meal_types: list[MealType] = MEAL_TYPES
) -> Week:
    """Place the recipes in the week, in order; see the module docstring."""
    meals = [m for m in MEAL_TYPES if m in meal_types]  # the day's order
    grid: dict[tuple[str, str], Slot] = {
        (day, meal): Slot(day, meal) for day in WEEKDAYS for meal in meals
    }
    spare: dict[str, int] = {}

    breakfast_slots = ["breakfast"] if "breakfast" in meals else []
    main_slots = [m for m in meals if m != "breakfast"]

    def slots_for(recipe: Recipe) -> list[str]:
        if recipe.course == "breakfast" and breakfast_slots:
            return breakfast_slots
        return main_slots or breakfast_slots

    def place(recipe: Recipe, days, leftover: bool, latest_first: bool = False) -> int | None:
        """The first free slot for `recipe` on one of `days`; the day it took."""
        meals_of_day = slots_for(recipe)
        if latest_first:
            meals_of_day = list(reversed(meals_of_day))
        for index in days:
            for meal in meals_of_day:
                if grid[(WEEKDAYS[index], meal)].recipe is None:
                    grid[(WEEKDAYS[index], meal)] = Slot(
                        WEEKDAYS[index], meal, recipe.name, leftover=leftover
                    )
                    return index
        return None

    # Every recipe is cooked once before any leftovers are placed: otherwise
    # the first recipes' leftovers take the slots the last ones are cooked in.
    # The cookings are spread over the week (a recipe per day, or as even as
    # the count allows), at the day's last meal — tonight's dinner is
    # tomorrow's lunch — so leftovers never have to last past their window.
    cooked: dict[int, int] = {}
    days = len(WEEKDAYS)
    for group in (
        [i for i, r in enumerate(recipes) if slots_for(r) == breakfast_slots],
        [i for i, r in enumerate(recipes) if slots_for(r) != breakfast_slots],
    ):
        for rank, position in enumerate(group):
            start = rank * days // len(group) if len(group) <= days else rank % days
            order = [*range(start, days), *range(0, start)]
            day = place(recipes[position], order, leftover=False, latest_first=True)
            if day is not None:
                cooked[position] = day

    # Then the leftovers: one meal a day, within MAX_DAYS_PER_COOKING of cooking.
    for position, recipe in enumerate(recipes):
        made = portions(recipe, household_size)
        placed = 0
        if position in cooked:
            placed, last = 1, cooked[position]
            window_end = min(len(WEEKDAYS), cooked[position] + MAX_DAYS_PER_COOKING)
            while placed < made:
                day = place(recipe, range(last + 1, window_end), leftover=True)
                if day is None:
                    break
                placed, last = placed + 1, day
        if made > placed:
            spare[recipe.name] = made - placed

    return Week(slots=list(grid.values()), spare_portions=spare)
