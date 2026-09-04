"""EDEKA offer fetching and parsing.

The offers come from the XHR endpoint the store's "Angebote" page calls. The
cookies below were captured from a browser session; they go stale, at which
point the request starts coming back empty or as HTML and has to be recaptured.
"""

from __future__ import annotations

import pandas as pd
import requests

AUTH_PROXY_URL = "https://www.edeka.de/api/auth-proxy/"

DEFAULT_MARKET_ID = "10001604"

COOKIES = {
    "EDEKA_PRIVACY": "1%40087%7C6%7C5030%40%4091%401759168772089%2C1759168772089%2C1792864772089%40",
    "EDEKA_PRIVACY_CENTER": "",
    "JSESSIONID": "868E369E9FD720B0A453D661690D2FE1",
    "atuserid": "%7B%22name%22%3A%22atuserid%22%2C%22val%22%3A%22OPT-OUT%22%2C%22options%22%3A%7B%22end%22%3A%222026-10-31T18%3A02%3A53.457Z%22%2C%22path%22%3A%22%2F%22%7D%7D",
    "TCPID": "12591202533522197673",
}

HEADERS = {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9,de;q=0.8,vi;q=0.7",
    "priority": "u=1, i",
    "referer": "https://www.edeka.de/eh/s%C3%BCdwest/edeka-frank-erlachstra%C3%9Fe-45/angebote.jsp",
    "sec-ch-ua": '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
}

# Fields kept from the offer payload; the rest is display metadata.
OFFER_COLUMNS = [
    "title",
    "price.value",
    "category.name",
    "descriptions",
    "validTill",
]


def fetch_offers(market_id: str = DEFAULT_MARKET_ID, limit: int = 999) -> dict:
    """Fetch the current reduced-price offers as the raw JSON payload."""
    params = {"path": f"api/offers?limit={limit}&marketId={market_id}"}
    response = requests.get(
        AUTH_PROXY_URL, params=params, cookies=COOKIES, headers=HEADERS, timeout=30
    )
    response.raise_for_status()
    return response.json()


def parse_offers(json_data: dict) -> pd.DataFrame:
    """Flatten the offer payload into a raw offers frame.

    Columns: title, price, category, descriptions, validTill.
    """
    df = pd.json_normalize(json_data["offers"])
    df = df[OFFER_COLUMNS]

    df = df.rename(columns={"price.value": "price", "category.name": "category"})

    df["price"] = df["price"].astype(float)
    # descriptions is a list per offer; the first entry carries the useful text.
    df["descriptions"] = df["descriptions"].str[0]
    df["validTill"] = pd.to_datetime(df["validTill"], errors="coerce")

    return df
