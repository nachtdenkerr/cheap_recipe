"""Pick items per category according to user preference.

Filters the classified offers frame down to what a given use case can actually
cook with. Diet is not decided here — see cheaprecipe.vocabulary.
"""

from __future__ import annotations

import logging

import pandas as pd

log = logging.getLogger(__name__)


# The classifier flags the specialised uses only. Ordinary savoury cooking is
# the residual case, so "cooking" filters on nothing beyond can_cook.
USE_COLUMNS = {
    "baking": "use_baking",
    "drinks": "use_drinks",
}

USE_CHOICES = ("cooking", *USE_COLUMNS)


def cookable(df: pd.DataFrame) -> pd.DataFrame:
    """Offers the classifier judged usable as a recipe ingredient."""
    return df[df["can_cook"] == True]  # pandas mask, not a bool test


def select_items(df: pd.DataFrame, use: str = "cooking") -> pd.DataFrame:
    """Filter offers by use case.

    No diet filter: an item satisfies many diets at once, so the recipe is the
    only place the question is decidable. Pass the user's diet to
    matching.retrieval.complex_search instead.

    use: one of USE_CHOICES. "baking" and "drinks" require that flag;
        "cooking" is the residual case and adds no filter of its own.
    """
    if use not in USE_CHOICES:
        raise ValueError(f"unknown use {use!r}; expected one of {USE_CHOICES}")

    before = len(df)

    df = cookable(df)
    after_cookable = len(df)

    if use in USE_COLUMNS:
        df = df[df[USE_COLUMNS[use]] == True]  # pandas mask, not a bool test

    # The attrition chain is the whole story when a run returns no recipes.
    log.info(
        "selected %d/%d offers: can_cook %d -> use=%s %d",
        len(df), before, after_cookable, use, len(df),
    )
    if df.empty:
        log.warning(
            "no offers survived selection for use=%s — retrieval has nothing to query on",
            use,
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

