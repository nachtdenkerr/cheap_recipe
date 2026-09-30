"""pipeline — file names, and what build_recipes writes when; no network."""

import json

import pandas as pd

from cheaprecipe import pipeline
from cheaprecipe.matching import retrieval
from cheaprecipe.selection import select


def test_checkpoints_are_named_per_store():
    assert pipeline.raw_offers_csv("edeka") == "edeka_offers_raw.csv"
    assert pipeline.translated_offers_csv("aldi") == "aldi_offers_translated.csv"
    assert pipeline.classified_offers_csv("edeka") == "edeka_offers_classified.csv"
    assert pipeline.recipes_json("aldi") == "aldi_recipes.json"


def _run(tmp_path, monkeypatch, **kwargs):
    """build_recipes with the selection and the API stubbed; records API calls."""
    data = tmp_path
    pd.DataFrame({"ingredient_en": ["onion"]}).to_csv(data / "edeka_offers_classified.csv", index=False)
    (data / "edeka_recipes.json").write_text(json.dumps([{"id": 99, "title": "previous run"}]))
    monkeypatch.setattr(pipeline, "DATA_DIR", data)
    monkeypatch.setattr(select, "select_items", lambda df, use: df)
    monkeypatch.setattr(select, "ingredient_names", lambda df, limit: ["onion"])

    calls = []
    returned = kwargs.pop("returned", [{"id": 1}])

    def complex_search(names, **kw):
        calls.append(("complexSearch", kw))
        return returned

    def find_by_ingredients(names, number):
        calls.append(("findByIngredients", {}))
        return returned

    monkeypatch.setattr(retrieval, "complex_search", complex_search)
    monkeypatch.setattr(retrieval, "find_by_ingredients", find_by_ingredients)
    monkeypatch.setattr(retrieval, "with_information", lambda found: found)

    kept = pipeline.build_recipes(**kwargs)
    written = json.loads((data / "edeka_recipes.json").read_text())
    return kept, written, calls


def test_a_cuisine_goes_to_complex_search(tmp_path, monkeypatch):
    _, written, calls = _run(tmp_path, monkeypatch, cuisine=["Thai"])
    assert [name for name, _ in calls] == ["complexSearch"]
    assert calls[0][1]["cuisine"] == ["Thai"]
    assert written == [{"id": 1}]


def test_no_preference_uses_find_by_ingredients(tmp_path, monkeypatch):
    _, _, calls = _run(tmp_path, monkeypatch)
    assert [name for name, _ in calls] == ["findByIngredients"]


def test_an_empty_result_leaves_the_last_recipes_alone(tmp_path, monkeypatch):
    kept, written, _ = _run(tmp_path, monkeypatch, cuisine=["Thai"], returned=[])
    assert kept == []
    assert written == [{"id": 99, "title": "previous run"}]


def test_each_branch_has_its_own_files():
    # The default branch keeps the plain names; another one cannot overwrite them.
    assert pipeline.classified_offers_csv("edeka", "10001604") == "edeka_offers_classified.csv"
    assert pipeline.raw_offers_csv("edeka", "8003153") == "edeka_8003153_offers_raw.csv"
    assert pipeline.classified_offers_csv("aldi", "1588161426582123") == "aldi_offers_classified.csv"
