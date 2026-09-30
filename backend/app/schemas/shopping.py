"""Request/response models for /shopping — mirrors `ShoppingListItem` in types.ts."""

from app.schemas import CamelModel
from app.schemas.recipes import Offer


class ShoppingListItem(CamelModel):
    """One thing to buy. Pantry staples never appear.

    With `offer`, it is on sale and its price is the offer's. Without, it is
    bought at the regular price: `estimated_price_cents` is the estimate for
    `quantity` packs, or None when no typical price is known.
    """

    # The generation_item row, so a tick can be saved back.
    id: int
    name: str
    offer: Offer | None = None
    # How much the recipes need, for a line that is not an offer ("700 g").
    amount: str | None = None
    # How many packs to buy.
    quantity: int
    estimated_price_cents: int | None = None
    # Titles of the recipes that need this item.
    used_by: list[str]
    checked: bool


class CheckUpdate(CamelModel):
    checked: bool
