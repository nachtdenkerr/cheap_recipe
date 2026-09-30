"""Pydantic contracts for the agent layer: what the planner emits, what the
critic returns.

These are the LLM-facing shapes. They mirror db/models.py but stay separate:
a model is free to return a plan that does not persist cleanly, and the
validation error is the signal that it did not.
"""

from datetime import date

from pydantic import BaseModel, Field

# The vocabularies are shared with the offer side — see cheaprecipe.vocabulary.
from cheaprecipe.vocabulary import (
    DEFAULT_MEAL_TYPES,
    CookingLevel,
    Course,
    Cuisine,
    DietType,
    MealType,
    Unit,
)


class UserPreference(BaseModel):
    """What the critic checks a plan against."""

    # Minutes free for cooking on each day, Monday first; 0 means no cooking.
    week_time_availability: list[int] | None = None
    # Free text, e.g. "nothing spicy".
    notes: str | None = None
    # Who eats, and which meals of the day the week covers — for the week grid.
    household_size: int = 1
    meal_types: list[MealType] = Field(default_factory=lambda: list(DEFAULT_MEAL_TYPES))


class Quantity(BaseModel):
    amount: float
    unit: Unit


class Ingredient(BaseModel):
    name: str
    quantity: Quantity
    ingredient_type: str | None = None
    kcal: int | None = None
    # False when the plan calls for something no current offer covers — the
    # cost calculation needs to know which lines it cannot price.
    from_offer: bool = True


class Appliance(BaseModel):
    name: str


class Recipe(BaseModel):
    name: str
    ingredients: list[Ingredient]
    appliances: list[Appliance] = Field(default_factory=list)
    cooking_instructions: str | None = None
    servings: int
    preparation_time: int | None = None
    cooking_time: int
    cooking_level: CookingLevel | None = None
    cuisine: list[Cuisine]
    total_kcal: int | None = None
    # What the dish is (agents/labels.py): a DishKind such as "pasta", and the
    # ingredient it is built on. None until the recipe has been labelled.
    kind: str | None = None
    main_ingredient: str | None = None
    # "breakfast" or "main"; None when unknown (planned as a main).
    course: Course | None = None

    # Set when the recipe came from retrieval rather than the planner, so it
    # can be reconciled with the recipe table instead of inserted twice.
    source: str | None = None
    external_id: str | None = None


class Item(BaseModel):
    name: str
    quantity: Quantity
    price: float
    price_per_unit: float
    price_per_unit_unit: Unit
    sale_start_date: date | None = None
    offer_id: int | None = None
    # The plain name a recipe uses for it (classify.py's base_ingredient):
    # "chicken breast" for marinated chicken steaks. Matched as well as `name`.
    base: str | None = None
    # A typical shelf price (calculation/regular_prices.py), not an offer:
    # bought at the regular price, and its cost is an estimate.
    estimated: bool = False


class Plan(BaseModel):
    recipes: list[Recipe]
    grocery_list: list[Item]
    diet_type: DietType | None = None
    total_cost: float | None = None


class Critique(BaseModel):
    """The critic's verdict on a plan, fed back to the planner if it fails."""

    passed: bool = Field(description="True only if the plan needs no changes.")
    assessment: str | None = Field(
        default=None, description="The critic's judgement of the week, in its words."
    )
    issues: list[str] = Field(
        default_factory=list, description="What is wrong with the plan, one per entry."
    )
    suggestions: list[str] = Field(
        default_factory=list, description="How to fix it, one per entry."
    )
    # By name: recipes are identified by name throughout the agent layer
    # (PlanningContext.find), and have no other id the model could see.
    exchange: list[str] = Field(
        default_factory=list,
        description="Exact names of the recipes in the plan that should be replaced.",
    )
