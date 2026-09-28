"""Request/response models for /auth — `User` mirrors types.ts."""

from typing import Annotated

from cheaprecipe.vocabulary import Allergen, CommonDiet, Cuisine
from pydantic import AfterValidator, Field

from app.schemas import CamelModel

# A shape check only; whether the address exists is not the API's to decide.
Email = Annotated[
    str,
    Field(max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
    AfterValidator(str.lower),
]


class SignupRequest(CamelModel):
    username: str = Field(min_length=3, max_length=30)
    email: Email
    password: str = Field(min_length=8, max_length=128)
    name: str | None = Field(default=None, max_length=120)


class LoginRequest(CamelModel):
    email: Email
    password: str


class User(CamelModel):
    name: str
    email: str
    diet_type: CommonDiet
    household_size: int
    weekly_budget_cents: int | None
    allergens: list[Allergen]
    market: str | None
    cuisines: list[Cuisine]
    # Ingredients to favour, and ones not allergic to but disliked.
    white_list: list[str]
    black_list: list[str]
    health_goal: str | None
    age: int | None
    gender: str | None
    # Minutes free for cooking each day, Monday first; null until set.
    week_time_availability: list[int] | None


class AuthSession(CamelModel):
    token: str
    user: User


def _clean_ingredients(names: list[str] | None) -> list[str] | None:
    """Trimmed, lower-cased, de-duplicated, blanks dropped, order kept."""
    if names is None:
        return None
    return list(dict.fromkeys(n.strip().lower() for n in names if n.strip()))


def _dedupe(values: list[str] | None) -> list[str] | None:
    return None if values is None else list(dict.fromkeys(values))


IngredientList = Annotated[
    list[Annotated[str, Field(max_length=80)]] | None,
    Field(default=None, max_length=100),
    AfterValidator(_clean_ingredients),
]


# 0 (no cooking that day) to 24 h, in 15-minute steps — what the Profile
# page's dropdowns offer.
DayMinutes = Annotated[int, Field(ge=0, le=24 * 60, multiple_of=15)]
WeekTime = Annotated[list[DayMinutes] | None, Field(min_length=7, max_length=7)]


class PreferencesUpdate(CamelModel):
    """Only the fields sent are changed."""

    name: str | None = Field(default=None, max_length=120)
    diet_type: CommonDiet | None = None
    household_size: int | None = Field(default=None, ge=1, le=20)
    weekly_budget_cents: int | None = Field(default=None, ge=0)
    allergens: Annotated[list[Allergen] | None, AfterValidator(_dedupe)] = None
    cuisines: list[Cuisine] | None = None
    black_list: IngredientList = None
    white_list: IngredientList = None
    health_goal: str | None = Field(default=None, max_length=120)
    age: int | None = Field(default=None, ge=1, le=120)
    gender: str | None = Field(default=None, max_length=30)
    # One entry per day, Monday first; null clears it.
    week_time_availability: WeekTime = None
    # A supermarket chain name, e.g. "EDEKA".
    market: str | None = None
