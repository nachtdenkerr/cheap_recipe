"""Request/response models for /markets — a branch a user can shop at."""

from app.schemas import CamelModel


class Market(CamelModel):
    # The address row — what POST /auth/me/preferences takes as homeMarketIds.
    id: int
    chain: str
    market_id: str
    name: str
    street: str | None = None
    postal_code: str | None = None
    city: str | None = None
