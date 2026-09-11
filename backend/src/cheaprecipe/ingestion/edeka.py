"""EDEKA offer fetching and parsing.

The offers come from the XHR endpoint the store's "Angebote" page calls. It
needs no authentication: no cookies, no API key, no custom headers.

Do not add a spoofed browser user-agent. The edge rejects a request that claims
to be Chrome or Firefox without the matching TLS fingerprint, so a browser UA
turns a working request into a 403 — as does any unrecognised custom UA. The
`requests` default gets through; send it as-is.
"""

from __future__ import annotations

import logging

import pandas as pd
import requests

AUTH_PROXY_URL = "https://www.edeka.de/api/auth-proxy/"

DEFAULT_MARKET_ID = "10001604"

# Fields kept from the offer payload; the rest is display metadata.
OFFER_COLUMNS = [
    "title",
    "price.value",
    "category.name",
    "descriptions",
    "validTill",
]


log = logging.getLogger(__name__)


class OfferFetchError(RuntimeError):
    """The offers endpoint did not return a usable payload."""


def fetch_offers(market_id: str = DEFAULT_MARKET_ID, limit: int = 999) -> dict:
    """Fetch the current reduced-price offers as the raw JSON payload.

    Raises OfferFetchError rather than letting a non-JSON body surface as a
    decode error: when the edge blocks a request it answers with HTML, which is
    otherwise reported as a confusing JSONDecodeError.
    """
    params = {"path": f"api/offers?limit={limit}&marketId={market_id}"}
    log.debug("GET %s market_id=%s limit=%s", AUTH_PROXY_URL, market_id, limit)
    response = requests.get(AUTH_PROXY_URL, params=params, timeout=30)

    if response.status_code == 403:
        raise OfferFetchError(
            "edeka.de refused the request (HTTP 403). This usually means a "
            "user-agent header was added — the endpoint wants the plain "
            "`requests` default, not a spoofed browser UA."
        )

    response.raise_for_status()

    content_type = response.headers.get("content-type", "")
    if "json" not in content_type:
        raise OfferFetchError(
            f"Expected JSON but got {content_type or 'an unknown content type'}. "
            "The endpoint contract may have changed."
        )

    log.debug(
        "edeka responded %s, %s bytes", response.status_code, len(response.content)
    )
    return response.json()


def parse_offers(json_data: dict) -> pd.DataFrame:
    """Flatten the offer payload into a raw offers frame.

    Columns: title, price, category, descriptions, validTill.
    """
    offers = json_data.get("offers")
    if not offers:
        raise OfferFetchError(
            f"The response carried no offers — check that marketId is valid. "
            f"Payload keys: {sorted(json_data)}"
        )

    df = pd.json_normalize(offers)

    missing = [column for column in OFFER_COLUMNS if column not in df.columns]
    if missing:
        raise OfferFetchError(
            f"Offer payload is missing expected column(s): {missing}. "
            f"The endpoint contract may have changed; got: {sorted(df.columns)}"
        )

    df = df[OFFER_COLUMNS]

    df = df.rename(columns={"price.value": "price", "category.name": "category"})

    df["price"] = df["price"].astype(float)
    # descriptions is a list per offer; the first entry carries the useful text.
    df["descriptions"] = df["descriptions"].str[0]
    df["validTill"] = pd.to_datetime(df["validTill"], errors="coerce")

    undated = int(df["validTill"].isna().sum())
    if undated:
        log.warning("%d/%d offers have an unparseable validTill", undated, len(df))

    log.info("parsed %d offers in %d categories", len(df), df["category"].nunique())
    return df
