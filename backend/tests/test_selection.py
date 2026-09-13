"""Deterministic tests for offer selection — no LLM, no network."""

import pandas as pd
import pytest

from cheaprecipe.selection import select

OFFERS = pd.DataFrame(
    {
        "ingredient_en": ["onion", "milk", "prosecco", "bread", "cleaning spray"],
        "price": [0.99, 1.19, 6.99, 1.49, 2.99],
        "can_cook": [True, True, True, True, False],
        "diet_type": ["vegan", "vegetarian", "vegan", "vegetarian", "normal"],
        # The classifier flags only the specialised uses.
        "use_baking": [False, True, False, True, False],
        "use_drinks": [False, True, True, False, False],
    }
)


def names(df):
    return sorted(df["ingredient_en"].tolist())


def test_cooking_is_the_residual_case():
    """"cooking" adds no flag filter — can_cook already gates it."""
    assert names(select.select_items(OFFERS)) == ["bread", "milk", "onion", "prosecco"]


def test_baking_and_drinks_require_their_flag():
    assert names(select.select_items(OFFERS, use="baking")) == ["bread", "milk"]
    assert names(select.select_items(OFFERS, use="drinks")) == ["milk", "prosecco"]


def test_non_cookable_is_never_selected():
    for use in select.USE_CHOICES:
        assert "cleaning spray" not in names(select.select_items(OFFERS, use=use))


def test_diet_narrows_further():
    assert names(select.select_items(OFFERS, diet_type="vegan")) == ["onion", "prosecco"]
    assert names(select.select_items(OFFERS, diet_type="vegetarian", use="baking")) == [
        "bread",
        "milk",
    ]


@pytest.mark.parametrize("bad", ["snacking", "use_cooking", ""])
def test_unknown_use_is_rejected(bad):
    with pytest.raises(ValueError, match="unknown use"):
        select.select_items(OFFERS, use=bad)


def test_unknown_diet_is_rejected():
    with pytest.raises(ValueError, match="unknown diet_type"):
        select.select_items(OFFERS, diet_type="carnivore")


def test_ingredient_names_are_cheapest_first_and_deduplicated():
    df = pd.DataFrame(
        {
            "ingredient_en": ["milk", "onion", "milk"],
            "price": [1.19, 0.99, 1.09],
        }
    )
    assert select.ingredient_names(df) == ["onion", "milk"]
    assert select.ingredient_names(df, limit=1) == ["onion"]
