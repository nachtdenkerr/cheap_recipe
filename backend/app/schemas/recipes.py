"""Request/response models for /recipes — mirrors `Recipe` in types.ts."""

from datetime import date
from typing import Literal

from app.schemas import CamelModel
from cheaprecipe.vocabulary import CommonDiet, DietType


class Offer(CamelModel):
    id: int
    # Original German product name, as printed in the shop.
    title: str
    ingredient_en: str | None = None
    category: str | None = None
    # The branch it is on offer at ("EDEKA Frank"), for users with several.
    market: str | None = None
    price_cents: int
    valid_from: date | None = None
    valid_till: date | None = None
    # The offer side has no diet (see vocabulary.py); kept for the frontend type.
    diet_type: DietType | None = None


class RecipeIngredient(CamelModel):
    name: str
    # Human-readable, e.g. "400 g".
    amount: str
    offer: Offer | None = None
    # A staple assumed at home (calculation/pantry.py). A line that is neither
    # on offer nor pantry is bought at the regular price.
    pantry: bool = False
    # For a line bought at the regular price: the estimated shelf price of the
    # pack it comes in (calculation/regular_prices.py). None when not known.
    regular_price_cents: int | None = None


class Nutrition(CamelModel):
    """Per serving."""

    kcal: int
    protein_g: float
    carbs_g: float
    fat_g: float


class RecipeCost(CamelModel):
    total_cents: int
    per_serving_cents: int
    leftover_cents: int
    # The part of total_cents that is an estimate at regular prices: when
    # above 0 the cost is shown as "≈ ...".
    estimated_cents: int
    # Lines to buy with no price at all, not even an estimate: when above 0,
    # the totals are a floor, shown as "from ...".
    unpriced_count: int


class Recipe(CamelModel):
    id: str
    title: str
    summary: str
    servings: int
    minutes: int
    diet_type: CommonDiet
    allergens: list[str]
    ingredients: list[RecipeIngredient]
    steps: list[str]
    cost: RecipeCost
    nutrition: Nutrition
    rationale: str
    # Hearted by the user (stored on their preferences).
    is_favourite: bool
    # Chosen for this week — only these recipes fill the shopping list.
    in_meal_plan: bool
    # Eaten as a breakfast, or at lunch and dinner.
    course: Literal["breakfast", "main"] = "main"
