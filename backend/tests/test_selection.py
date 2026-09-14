"""Deterministic tests for offer selection — no LLM, no network."""

import pandas as pd
import pytest

from cheaprecipe import vocabulary
from cheaprecipe.agents import contracts
from cheaprecipe.selection import select

OFFERS = pd.DataFrame(
    {
        "ingredient_en": ["onion", "milk", "prosecco", "bread", "cleaning spray"],
        "price": [0.99, 1.19, 6.99, 1.49, 2.99],
        "can_cook": [True, True, True, True, False],
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


@pytest.mark.parametrize("bad", ["snacking", "use_cooking", ""])
def test_unknown_use_is_rejected(bad):
    with pytest.raises(ValueError, match="unknown use"):
        select.select_items(OFFERS, use=bad)


def test_ingredient_names_are_cheapest_first_and_deduplicated():
    df = pd.DataFrame(
        {
            "ingredient_en": ["milk", "onion", "milk"],
            "price": [1.19, 0.99, 1.09],
        }
    )
    assert select.ingredient_names(df) == ["onion", "milk"]
    assert select.ingredient_names(df, limit=1) == ["onion"]


# --- the shared vocabulary --------------------------------------------------


def test_contracts_and_selection_share_one_definition():
    """Not a copy that can drift — the same object."""
    assert contracts.DietType is vocabulary.DietType
    assert contracts.Cuisine is vocabulary.Cuisine
    assert contracts.CookingLevel is vocabulary.CookingLevel


def test_runtime_tuples_are_derived_from_the_literals():
    from typing import get_args

    assert vocabulary.DIET_TYPES == get_args(contracts.DietType)
    assert vocabulary.CUISINES == get_args(contracts.Cuisine)


def test_selection_has_no_diet_filter():
    """Diet is decided on the recipe; offers carry no diet at all."""
    with pytest.raises(TypeError):
        select.select_items(OFFERS, diet_type="vegan")
    assert not hasattr(select, "DIET_ALLOWED")


def test_normal_sends_no_diet_to_spoonacular():
    """"normal" is our word for no restriction — Spoonacular would reject it."""
    assert vocabulary.spoonacular_diet("normal") is None
    assert vocabulary.spoonacular_diet(None) is None
    assert vocabulary.spoonacular_diet("ketogenic") == "ketogenic"
