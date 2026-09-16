"""Raw offers -> canonical items.

Deterministic half of normalization: drop non-food categories, tidy titles, and
derive validFrom from the weekday named in the title. The LLM half (German
title -> English ingredient) lives in `ingredients.py`.
"""

from __future__ import annotations

import logging

import pandas as pd

from cheaprecipe import vocabulary
from cheaprecipe.normalization import quantity

log = logging.getLogger(__name__)

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


def drop_non_food(df: pd.DataFrame, store: vocabulary.Store) -> pd.DataFrame:
    """Remove the categories and descriptions that are not food.

    `store` picks the vocabulary: each chain names its departments its own way,
    so the lists live per store in `excluded_categories.yml`. It is required
    rather than defaulted because the wrong vocabulary does not fail — it
    quietly matches nothing and lets every shampoo through.
    """
    excluded = df["category"].isin(vocabulary.excluded_categories(store))
    if excluded.any():
        by_category = df.loc[excluded, "category"].value_counts().to_dict()
        log.info("dropped %d non-food offers by category: %s", int(excluded.sum()), by_category)
    df = df[~excluded]

    for term in vocabulary.excluded_description_terms(store):
        matches = df["descriptions"].str.contains(term, na=False)
        if matches.any():
            log.info("dropped %d offers matching description term %r", int(matches.sum()), term)
        df = df[~matches]

    return df


def drop_unpriced(df: pd.DataFrame) -> pd.DataFrame:
    """Remove offers the payload carries no price for.

    These are percentage-discount promotions ("20% off"), which quote no
    absolute price. A 0.00 would otherwise read as free and win every ranking,
    and nothing downstream can derive a price per unit for them.
    """
    unpriced = df["price"].isna() | (df["price"] <= 0)
    if unpriced.any():
        examples = df.loc[unpriced, "title"].head(3).tolist()
        log.info(
            "dropped %d offers with no price (discount promotions), e.g. %s",
            int(unpriced.sum()), examples,
        )
    return df[~unpriced]


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


def clean_offers(df: pd.DataFrame, store: vocabulary.Store) -> pd.DataFrame:
    """Full deterministic pass: drop non-food and unpriced, normalize, sort,
    then parse quantity and price per unit out of the descriptions.

    `store` is the chain the frame came from; see `drop_non_food`.
    """
    before = len(df)
    df = drop_non_food(df, store)
    df = drop_unpriced(df)
    df = normalize(df)
    df = df.sort_values(by=["category", "title"]).reset_index(drop=True)
    df = quantity.add_quantity_columns(df)
    log.info("cleaned offers: %d in -> %d out (%d dropped)", before, len(df), before - len(df))
    return df
