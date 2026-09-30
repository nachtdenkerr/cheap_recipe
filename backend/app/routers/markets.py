"""Supermarket search, for choosing home markets in the profile.

Searches the chains' own market finders (cheaprecipe/ingestion/markets.py)
and remembers every branch found as an Address, so the profile can refer to
it by id. When EDEKA's finder is unreachable, the branches already known are
searched instead.
"""

import logging

from fastapi import APIRouter, Query
from sqlalchemy import or_, select

from app.deps import CurrentUser, SessionDep
from app.presenters import market_out
from app.schemas.markets import Market
from cheaprecipe.db.load import upsert_market
from cheaprecipe.db.models import Address
from cheaprecipe.ingestion import markets

log = logging.getLogger(__name__)

router = APIRouter(prefix="/markets", tags=["markets"])

MAX_RESULTS = 10


@router.get("", response_model=list[Market])
def search_markets(
    user: CurrentUser,
    session: SessionDep,
    q: str = Query(min_length=2, max_length=80),
) -> list[Market]:
    """Branches whose name, street, town or postcode match `q`."""
    try:
        found = markets.search(q, limit=MAX_RESULTS)
    except Exception as exc:  # noqa: BLE001 — network, EDEKA changed: use what we know
        log.warning("market search %r failed, searching known branches: %s", q, exc)
        pattern = f"%{q.strip()}%"
        rows = session.scalars(
            select(Address)
            .where(
                or_(
                    Address.name.ilike(pattern),
                    Address.street.ilike(pattern),
                    Address.city.ilike(pattern),
                    Address.postal_code.ilike(pattern),
                    Address.market_id == q.strip(),
                )
            )
            .order_by(Address.name)
            .limit(MAX_RESULTS)
        )
        return [market_out(row) for row in rows]
    branches = [upsert_market(session, info) for info in found]
    session.commit()
    return [market_out(branch) for branch in branches]
