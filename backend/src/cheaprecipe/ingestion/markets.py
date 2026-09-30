"""Finding a user's supermarket: branch search by name, street, town or postcode.

Offers are per branch for EDEKA — the market id is what ingestion/edeka.py
fetches them by — so a home market has to be a branch, not just "EDEKA".
EDEKA's own market finder answers through the same unauthenticated proxy as
the offers, with each branch's id, name and address.

ALDI SÜD has no per-branch offers: ingestion/aldi.py reads one category page
for the whole country. So there is a single ALDI SÜD entry, found by name.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

from cheaprecipe.ingestion import aldi, edeka

log = logging.getLogger(__name__)

MARKET_SEARCH_PATH = "api/marketsearch/markets"
TIMEOUT = 15


@dataclass(frozen=True)
class MarketInfo:
    chain: str  # a vocabulary.Store: "edeka" or "aldi"
    market_id: str
    name: str
    street: str | None = None
    postal_code: str | None = None
    city: str | None = None


ALDI_SUED = MarketInfo(
    chain="aldi", market_id=aldi.DEFAULT_CATEGORY_ID, name="ALDI SÜD",
    city="all branches",
)


def search_edeka(query: str, limit: int = 10) -> list[MarketInfo]:
    """EDEKA branches matching `query`, as EDEKA's market finder ranks them."""
    response = requests.get(
        edeka.AUTH_PROXY_URL,
        params={"path": f"{MARKET_SEARCH_PATH}?searchstring={requests.utils.quote(query)}&limit={limit}"},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    markets = []
    for market in response.json().get("markets") or []:
        address = (market.get("contact") or {}).get("address") or {}
        city = address.get("city") or {}
        markets.append(
            MarketInfo(
                chain="edeka",
                market_id=str(market["id"]),
                name=market.get("name") or "EDEKA",
                street=address.get("street"),
                postal_code=city.get("zipCode"),
                city=city.get("name"),
            )
        )
    log.info("EDEKA market search %r: %d found", query, len(markets))
    return markets


def search(query: str, limit: int = 10) -> list[MarketInfo]:
    """Branches of every chain we ingest that match `query`.

    Raises when EDEKA's search is unreachable; the API then falls back to the
    branches it already knows (app/routers/markets.py).
    """
    query = query.strip()
    lowered = query.lower()
    # A query naming ALDI is only about ALDI: EDEKA's finder would answer it
    # with fuzzy matches ("Klein").
    if "aldi" in lowered:
        return [ALDI_SUED]
    # "al", "ald" — a prefix of the name — may be either.
    found = [ALDI_SUED] if len(lowered) >= 2 and "aldi süd".startswith(lowered) else []
    return found + search_edeka(query, limit)
