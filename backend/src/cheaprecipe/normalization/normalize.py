"""Raw offers -> canonical items.

Deterministic half of normalization: drop non-food categories, tidy titles, and
derive validFrom from the weekday named in the title. The LLM half (German
title -> English ingredient) lives in `ingredients.py`.
"""

from __future__ import annotations

import pandas as pd

# Categories that never produce a recipe ingredient.
EXCLUDED_CATEGORIES = ["Drogerie", "Tiernahrung", "Non-Food"]

# Non-food items that slip through inside food categories (cookware, decor).
EXCLUDED_DESCRIPTION_TERMS = ["Topf", "Deko"]

WEEKDAY_MAP = {
    "Montag": 0,
    "Dienstag": 1,
    "Mittwoch": 2,
    "Donnerstag": 3,
    "Freitag": 4,
    "Samstag": 5,
    "Sonntag": 6,
}

# Offers with no weekday in the title run the whole week, i.e. from Monday.
DEFAULT_WEEKDAY = 0


def extract_weekday_from_title(title: str | None) -> int | None:
    """Return the weekday index named in the title, or None."""
    if not isinstance(title, str):
        return None

    for name in WEEKDAY_MAP:
        if name in title:
            return WEEKDAY_MAP[name]
    return None


def drop_non_food(df: pd.DataFrame) -> pd.DataFrame:
    """Remove the categories and descriptions that are not food."""
    df = df[~df["category"].isin(EXCLUDED_CATEGORIES)]
    for term in EXCLUDED_DESCRIPTION_TERMS:
        df = df[~df["descriptions"].str.contains(term, na=False)]
    return df


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Clean titles, coerce types, and add weekday_in_title / validFrom."""
    df = df.copy()

    df["title"] = (
        df["title"]
        .str.replace("\xa0", " ", regex=False)
        .str.replace(r"[⁰-₟²³¹]", "", regex=True)  # superscripts
        .str.strip()
    )

    df["price"] = df["price"].astype(float)

    df["weekday_in_title"] = df["title"].apply(extract_weekday_from_title)

    df["validTill"] = pd.to_datetime(df["validTill"], errors="coerce")
    current_weekday = df["validTill"].dt.weekday
    weekday_target = df["weekday_in_title"].fillna(DEFAULT_WEEKDAY)

    df["validFrom"] = df["validTill"] - pd.to_timedelta(
        current_weekday - weekday_target, unit="D"
    )

    # The weekday is captured in validFrom now, so strip it from the title.
    for day_name in WEEKDAY_MAP:
        df["title"] = (
            df["title"]
            .str.replace(f"Ab {day_name} erhältlich: ", "", regex=False)
            .str.replace(f"Am {day_name} erhältlich: ", "", regex=False)
        )

    return df


def clean_offers(df: pd.DataFrame) -> pd.DataFrame:
    """Full deterministic pass: drop non-food, normalize, sort."""
    df = drop_non_food(df)
    df = normalize(df)
    return df.sort_values(by=["category", "title"]).reset_index(drop=True)
