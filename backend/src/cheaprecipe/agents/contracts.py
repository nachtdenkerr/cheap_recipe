"""Pydantic contracts for the agent layer: what the planner emits, what the
critic returns.

These are the LLM-facing shapes. They mirror db/models.py but stay separate:
a model is free to return a plan that does not persist cleanly, and the
validation error is the signal that it did not.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

# A closed set the critic and the UI can both rely on; DIET_TYPES in
# selection/select.py is the matching vocabulary on the offers side.
CookingLevel = Literal["easy", "medium", "hard"]
DietType = Literal["vegan", "vegetarian", "normal"]


class Quantity(BaseModel):
    amount: float
    unit: str


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
    cooking_instructions: str
    servings: int
    preparation_time: int
    cooking_time: int
    cooking_level: CookingLevel
    cuisine: str
    total_kcal: int

    # Set when the recipe came from retrieval rather than the planner, so it
    # can be reconciled with the recipe table instead of inserted twice.
    source: str | None = None
    external_id: str | None = None


class Item(BaseModel):
    name: str
    quantity: Quantity
    price: float
    price_per_unit: float
    sale_start_date: date | None = None
    offer_id: int | None = None


class Plan(BaseModel):
    recipes: list[Recipe]
    grocery_list: list[Item]
    diet_type: DietType | None = None
    total_cost: float | None = None


class Critique(BaseModel):
    passed: bool
    waste_grams: float
    total_cost: float
    nutrition_ok: bool
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
