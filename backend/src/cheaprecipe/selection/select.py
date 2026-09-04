"""Pick items per category according to user preference.

Filters the classified offers frame down to what a given diet and use case can
actually cook with.
"""

from __future__ import annotations

import pandas as pd

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

    df = cookable(df)
    df = df[df["diet_type"].isin(DIET_ALLOWED[diet_type])]
    return df[df[USE_COLUMNS[use]] == True]  # noqa: E712


def ingredient_names(df: pd.DataFrame, limit: int | None = None) -> list[str]:
    """Distinct English ingredient names, cheapest first — the retrieval input."""
    names = (
        df.sort_values("price")["ingredient_en"].dropna().drop_duplicates().tolist()
    )
    return names[:limit] if limit else names
