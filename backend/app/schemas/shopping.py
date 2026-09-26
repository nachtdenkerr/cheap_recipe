"""Request/response models for /shopping — mirrors `ShoppingListItem` in types.ts."""

from app.schemas import CamelModel
from app.schemas.recipes import Offer


class ShoppingListItem(CamelModel):
    # The generation_item row, so a tick can be saved back.
    id: int
    offer: Offer
    # How many packs to buy.
    quantity: int
    # Titles of the recipes that need this item.
    used_by: list[str]
    checked: bool


class CheckUpdate(CamelModel):
    checked: bool
