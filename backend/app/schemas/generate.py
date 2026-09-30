"""Request/response models for /generate."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, model_validator

from app.schemas import CamelModel
from app.schemas.auth import IngredientList
from app.schemas.recipes import Recipe


class GenerateRequest(CamelModel):
    number_of_meals: int = Field(default=5, ge=1, le=14)


def _blank_to_none(text: str | None) -> str | None:
    return text.strip() or None if text is not None else None


class RefineRequest(CamelModel):
    """A follow-up request against this week's plan. Counts towards the quota.

    - "replace": swap the recipes the user did not plan for new ones;
    - "pantry": the same, but favouring recipes that use `pantry_items`.
    """

    mode: Literal["replace", "pantry"]
    # How many new recipes; defaults to the number of unplanned ones (min 1).
    count: int | None = Field(default=None, ge=1, le=5)
    pantry_items: IngredientList = None
    # Free text for the planner agent and the critic ("nothing spicy").
    note: Annotated[str | None, Field(default=None, max_length=300), AfterValidator(_blank_to_none)] = None

    @model_validator(mode="after")
    def _pantry_needs_items(self) -> "RefineRequest":
        if self.mode == "pantry" and not self.pantry_items:
            raise ValueError("pantry mode needs at least one item")
        return self


class RefineQuota(CamelModel):
    used: int
    limit: int
    remaining: int
    resets_at: datetime
    # Whether this week's first plan exists; until then there is nothing to refine.
    weekly_plan_done: bool


class RefineResponse(CamelModel):
    recipes: list[Recipe]
    quota: RefineQuota
