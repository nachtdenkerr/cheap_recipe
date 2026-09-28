"""Request/response models for /recipes — mirrors `Recipe` in types.ts."""

from datetime import date

from cheaprecipe.vocabulary import CommonDiet, DietType

from app.schemas import CamelModel


class Offer(CamelModel):
    id: int
    # Original German product name, as printed in the shop.
    title: str
    ingredient_en: str | None = None
    category: str | None = None
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
    # True when no offer in the plan covers it — assumed to be at home.
    pantry: bool = False


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
