"""Deterministic tests for the normalization stage — no LLM, no network."""

import pandas as pd

from cheaprecipe.normalization import normalize


def test_extract_weekday_from_title():
    assert normalize.extract_weekday_from_title("Ab Donnerstag erhältlich: Grana Padano") == 3
    assert normalize.extract_weekday_from_title("Avocados") is None
    assert normalize.extract_weekday_from_title(None) is None


def test_drop_non_food():
    df = pd.DataFrame(
        {
            "title": ["Avocados", "Hundefutter", "Adventsgesteck"],
            "category": ["Obst & Gemüse", "Tiernahrung", "Obst & Gemüse"],
            "descriptions": ["Stück", "800 g", "im Topf"],
        }
    )

    kept = normalize.drop_non_food(df)

    assert kept["title"].tolist() == ["Avocados"]


def test_normalize_derives_valid_from_and_cleans_title():
    df = pd.DataFrame(
        {
            "title": ["Ab Donnerstag erhältlich: Grana\xa0Padano¹ ", "Avocados"],
            "price": ["1.99", "0.99"],
            "descriptions": ["500 g", "Stück"],
            "validTill": ["2025-11-22", "2025-11-22"],  # a Saturday
        }
    )

    out = normalize.normalize(df)

    assert out["title"].tolist() == ["Grana Padano", "Avocados"]
    assert out["price"].tolist() == [1.99, 0.99]
    assert out["weekday_in_title"][0] == 3
    assert pd.isna(out["weekday_in_title"][1])
    # Thursday-only offer starts on the Thursday; the rest start on Monday.
    assert out["validFrom"].dt.strftime("%Y-%m-%d").tolist() == ["2025-11-20", "2025-11-17"]
