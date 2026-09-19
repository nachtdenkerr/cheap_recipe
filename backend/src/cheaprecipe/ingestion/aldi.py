"""ALDI SÜD offer fetching and parsing.

Unlike EDEKA, ALDI SÜD exposes no offers endpoint. The category page is a
server-rendered Nuxt app, and its commerce API (Spryker, behind
api.aldi-sued.de) is not reachable without the front end's own credentials.
What *is* reachable is the hydration payload the server ships inside the page:
a `<script id="__NUXT_DATA__">` block holding every product the page renders,
already structured. We read the offers out of that.

The payload is devalue-encoded: one flat array where an integer is a reference
to another slot. `_hydrate` resolves those references; see `_products`.

The page paginates at 30 products, so `fetch_offers` walks `?page=N` until it
has the `totalCount` the payload reports.

No authentication, no headers: as with EDEKA, send the request as `requests`
builds it by default.
"""

from __future__ import annotations

import json
import logging
import re

import pandas as pd
import requests

CATEGORY_URL = "https://www.aldi-sued.de/produkte/wochenangebote/k/{category_id}"

# "Wochenangebote" — the weekly offers, the ALDI equivalent of EDEKA's Angebote.
DEFAULT_CATEGORY_ID = "1588161426582123"

# The page's own page size; the payload reports it, this is only the fallback.
PAGE_SIZE = 30

# Stop rather than hammer the site if the pagination contract changes.
MAX_PAGES = 20

NUXT_DATA_RE = re.compile(
    r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)

# Devalue wraps reactive values as ["ShallowReactive", <index>] and friends.
_WRAPPERS = frozenset(
    {"Ref", "ShallowRef", "EmptyRef", "EmptyShallowRef", "Reactive", "ShallowReactive"}
)

# How deep a product subtree goes: product -> price/categories -> fields.
_HYDRATE_DEPTH = 6

# "1,00 €/1 kg" — the base price ALDI prints, in the fields we can reuse.
COMPARISON_RE = re.compile(r"(?P<amount>[\d.,]+)\s*€\s*/\s*1\s*(?P<unit>kg|l)\s*$")


log = logging.getLogger(__name__)


class OfferFetchError(RuntimeError):
    """The category page did not carry a usable offer payload."""


def _hydrate(raw: list, index: int, depth: int = _HYDRATE_DEPTH):
    """Resolve one devalue slot into plain Python, `depth` levels deep.

    The payload graph is cyclic (a product's category links back to the
    listing), so the depth cap is what terminates the walk, not a visited set.
    """
    if depth < 0:
        return None

    value = raw[index]
    if isinstance(value, list):
        if len(value) == 2 and value[0] in _WRAPPERS:
            return _hydrate(raw, value[1], depth)
        return [_hydrate(raw, item, depth - 1) for item in value]
    if isinstance(value, dict):
        return {key: _hydrate(raw, item, depth - 1) for key, item in value.items()}
    return value


def _payload(html: str) -> list:
    """Pull the devalue array out of one rendered category page."""
    match = NUXT_DATA_RE.search(html)
    if not match:
        raise OfferFetchError(
            "The page carried no __NUXT_DATA__ block — aldi-sued.de may have "
            "stopped server-rendering the listing, or blocked the request."
        )

    try:
        raw = json.loads(match.group(1))
    except json.JSONDecodeError as error:
        raise OfferFetchError(f"__NUXT_DATA__ is not valid JSON: {error}") from error

    if not isinstance(raw, list):
        raise OfferFetchError(
            f"Expected a devalue array, got {type(raw).__name__}. "
            "The payload contract may have changed."
        )
    return raw


def _products(raw: list) -> list[dict]:
    """Every product in the payload, found by shape rather than by path.

    A product is the only node carrying both `sku` and `price`, so we do not
    have to walk the route/component tree to reach the listing — which is the
    part of the payload most likely to be reshuffled by a front-end release.
    """
    return [
        _hydrate(raw, index)
        for index, value in enumerate(raw)
        if isinstance(value, dict) and "sku" in value and "price" in value
    ]


def _total_count(raw: list) -> int | None:
    """The result count the listing reports, used to drive pagination."""
    for value in raw:
        if isinstance(value, dict) and "pagination" in value:
            pagination = _hydrate(raw, value["pagination"])
            if isinstance(pagination, dict):
                return pagination.get("totalCount")
    return None


def fetch_offers(
    category_id: str = DEFAULT_CATEGORY_ID, limit: int | None = None
) -> dict:
    """Fetch the current weekly offers as a payload of product dicts.

    Walks the category's pages until it has every product the listing counts,
    or `limit` of them. Returns {"products": [...], "totalCount": int}, the
    shape `parse_offers` expects.
    """
    url = CATEGORY_URL.format(category_id=category_id)
    products: list[dict] = []
    seen: set[str] = set()
    total: int | None = None

    for page in range(1, MAX_PAGES + 1):
        params = {"page": page} if page > 1 else None
        log.debug("GET %s page=%s", url, page)
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()

        raw = _payload(response.text)
        if total is None:
            total = _total_count(raw)
            log.debug("listing reports %s products in total", total)

        # The same product can appear twice on a page (listing plus teaser).
        new = [p for p in _products(raw) if p.get("sku") not in seen]
        seen.update(p.get("sku") for p in new)
        products.extend(new)

        if not new:
            break
        if limit is not None and len(products) >= limit:
            products = products[:limit]
            break
        if total is not None and len(products) >= total:
            break
    else:
        log.warning("stopped after %d pages without reaching the end", MAX_PAGES)

    if total is not None and limit is None and len(products) != total:
        log.warning(
            "collected %d products but the listing counts %d", len(products), total
        )

    log.debug("aldi returned %d products over %d page(s)", len(products), page)
    return {"products": products, "totalCount": total}


def _description(product: dict) -> str | None:
    """Rebuild the one field EDEKA has and ALDI does not.

    Downstream (`normalization.quantity`) reads quantity, deposit and base
    price out of EDEKA's free-text description, which follows a fixed grammar:

        <amount> <unit>[, zzgl. <X> Pfand][, (1 kg = <Y>)]

    ALDI carries the same three facts as separate fields, so we write them back
    into that grammar rather than teach the parser a second dialect. The base
    price is ALDI's own, which keeps the parser's cross-check honest: it still
    derives the number independently and compares.

    Expect a handful of cross-check warnings on small items: ALDI rounds
    `sellingSize` to two decimals, so an 87,5 g bar is published as "0,09 kg"
    and the derived base price lands a few percent off the printed one. The
    printed one is the one that reaches `price_per_unit`, so the value is right
    and only the warning is noise.
    """
    price = product.get("price") or {}

    selling_size = product.get("sellingSize")
    if not selling_size:
        # No size and sold "ea" means loose goods priced by the piece — the one
        # case EDEKA writes as a bare "Stück", and the parser reads as one unit.
        if product.get("quantityUnit") == "ea":
            return "Stück"
        return None
    parts = [str(selling_size).strip()]

    deposit = price.get("bottleDepositDisplay")
    if price.get("bottleDeposit") and isinstance(deposit, str):
        amount = deposit.replace("\xa0", " ").replace("€", "").strip()
        parts.append(f"zzgl. {amount} Pfand")

    comparison = price.get("comparisonDisplay")
    if isinstance(comparison, str):
        # Units other than kg/l ("1,18 €/1 KG/ATG", a drained weight) have no
        # equivalent in the grammar; leaving them out beats guessing.
        match = COMPARISON_RE.search(comparison.replace("\xa0", " ").strip())
        if match:
            parts.append(f"(1 {match['unit']} = {match['amount']})")

    return ", ".join(parts)


def _category(product: dict) -> str | None:
    """The product's department — its top-level category, not its aisle.

    `categories` runs parent-first: ["Drogerie & Kosmetik", "Shampoo &
    Haarpflege"]. We keep the parent because that is the altitude EDEKA's
    `category` sits at, so one `excluded_categories.yml` entry per chain covers
    a whole department instead of every aisle inside it.
    """
    categories = product.get("categories") or []
    names = [c.get("name") for c in categories if isinstance(c, dict) and c.get("name")]
    return names[0] if names else None


def parse_offers(json_data: dict) -> pd.DataFrame:
    """Flatten the offer payload into a raw offers frame.

    Columns: title, price, category, descriptions, validTill — the same frame
    `ingestion.edeka.parse_offers` returns, so both feed `normalization`
    unchanged. validTill is always NaT: the weekly-offer payload carries no
    end date.
    """
    products = json_data.get("products")
    if not products:
        raise OfferFetchError(
            f"The payload carried no products — check that the category id is "
            f"valid. Payload keys: {sorted(json_data)}"
        )

    rows = []
    for product in products:
        price = product.get("price") or {}
        amount = price.get("amount")
        rows.append(
            {
                "title": product.get("name"),
                # ALDI quotes money in cents; every downstream sum is in euros.
                "price": None if amount is None else amount / 100,
                "category": _category(product),
                "descriptions": _description(product),
                "validTill": pd.NaT,
            }
        )

    df = pd.DataFrame(rows, columns=["title", "price", "category", "descriptions", "validTill"])

    df["price"] = df["price"].astype(float)
    df["validTill"] = pd.to_datetime(df["validTill"], errors="coerce")

    undescribed = int(df["descriptions"].isna().sum())
    if undescribed:
        log.warning(
            "%d/%d offers carry no selling size — quantity will not be derivable",
            undescribed, len(df),
        )

    log.info("parsed %d offers in %d categories", len(df), df["category"].nunique())
    return df
