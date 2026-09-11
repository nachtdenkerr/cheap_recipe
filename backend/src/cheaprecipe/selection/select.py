"""Pick items per category according to user preference.

Filters the classified offers frame down to what a given diet and use case can
actually cook with.
"""

from __future__ import annotations

import logging

import pandas as pd

log = logging.getLogger(__name__)

DIET_TYPES = ("vegan", "vegetarian", "normal")

# A vegan diet accepts only vegan items; a vegetarian one accepts both; "normal"
# accepts everything.
DIET_ALLOWED = {
    "vegan": {"vegan"},
    "vegetarian": {"vegan", "vegetarian"},
    "normal": {"vegan", "vegetarian", "normal"},
}

USE_COLUMNS = {
    "cooking": "use_cooking",
    "baking": "use_baking",
    "drinks": "use_drinks",
}


def cookable(df: pd.DataFrame) -> pd.DataFrame:
    """Offers the classifier judged usable as a recipe ingredient."""
    return df[df["can_cook"] == True]  # noqa: E712 — pandas mask, not a bool test


def select_items(
    df: pd.DataFrame,
    diet_type: str = "normal",
    use: str = "cooking",
) -> pd.DataFrame:
    """Filter offers by diet and use case.

    diet_type: one of DIET_TYPES — "normal" admits every item.
    use: one of USE_COLUMNS — which usage flag must be true.
    """
    if diet_type not in DIET_ALLOWED:
        raise ValueError(f"unknown diet_type {diet_type!r}; expected one of {DIET_TYPES}")
    if use not in USE_COLUMNS:
        raise ValueError(f"unknown use {use!r}; expected one of {tuple(USE_COLUMNS)}")

    before = len(df)

    df = cookable(df)
    after_cookable = len(df)

    df = df[df["diet_type"].isin(DIET_ALLOWED[diet_type])]
    after_diet = len(df)

    df = df[df[USE_COLUMNS[use]] == True]  # noqa: E712

    # The attrition chain is the whole story when a run returns no recipes.
    log.info(
        "selected %d/%d offers: can_cook %d -> diet=%s %d -> use=%s %d",
        len(df), before, after_cookable, diet_type, after_diet, use, len(df),
    )
    if df.empty:
        log.warning(
            "no offers survived selection for diet=%s use=%s — retrieval has nothing to query on",
            diet_type, use,
        )

    return df


def ingredient_names(df: pd.DataFrame, limit: int | None = None) -> list[str]:
    """Distinct English ingredient names, cheapest first — the retrieval input."""
    names = (
        df.sort_values("price")["ingredient_en"].dropna().drop_duplicates().tolist()
    )
    if limit and len(names) > limit:
        log.info("%d distinct ingredients, querying on the %d cheapest", len(names), limit)
    return names[:limit] if limit else names
