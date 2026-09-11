"""Raw offers -> canonical items.

Deterministic half of normalization: drop non-food categories, tidy titles, and
derive validFrom from the weekday named in the title. The LLM half (German
title -> English ingredient) lives in `ingredients.py`.
"""

from __future__ import annotations

import logging

import pandas as pd

log = logging.getLogger(__name__)

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
    excluded = df["category"].isin(EXCLUDED_CATEGORIES)
    if excluded.any():
        by_category = df.loc[excluded, "category"].value_counts().to_dict()
        log.info("dropped %d non-food offers by category: %s", int(excluded.sum()), by_category)
    df = df[~excluded]

    for term in EXCLUDED_DESCRIPTION_TERMS:
        matches = df["descriptions"].str.contains(term, na=False)
        if matches.any():
            log.info("dropped %d offers matching description term %r", int(matches.sum()), term)
        df = df[~matches]

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
    log.debug(
        "%d/%d titles name a weekday", int(df["weekday_in_title"].notna().sum()), len(df)
    )

    df["validTill"] = pd.to_datetime(df["validTill"], errors="coerce")
    undated = int(df["validTill"].isna().sum())
    if undated:
        # validFrom is derived from validTill, so these end up undated too.
        log.warning("%d/%d offers have no usable validTill — validFrom will be NaT", undated, len(df))
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
    before = len(df)
    df = drop_non_food(df)
    df = normalize(df)
    log.info("cleaned offers: %d in -> %d out (%d dropped)", before, len(df), before - len(df))
    return df.sort_values(by=["category", "title"]).reset_index(drop=True)
