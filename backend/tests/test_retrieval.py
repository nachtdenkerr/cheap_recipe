"""Retrieval tests — the request we build and the response we unwrap.

No network: `requests.get` is stubbed, so these assert on parameters rather
than on Spoonacular's data.
"""

import pytest

from cheaprecipe.matching import retrieval


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"unexpected status {self.status_code}")


@pytest.fixture
def sent(monkeypatch):
    """Capture the params of the last request instead of making one."""
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return FakeResponse(captured.get("payload", {"results": [], "totalResults": 0}))

    monkeypatch.setattr(retrieval.requests, "get", fake_get)
    return captured


def test_several_cuisines_go_in_one_request(sent):
    """Comma-separated is OR, so a cuisine list is one call, not one each."""
    retrieval.complex_search(["avocado"], cuisine=["italian", "mexican"], api_key="k")
    assert sent["params"]["cuisine"] == "italian,mexican"


def test_allergens_and_block_list_become_filters(sent):
    retrieval.complex_search(
        ["avocado"],
        diet="vegan",
        intolerances=["dairy", "peanut"],
        exclude_ingredients=["cilantro"],
        api_key="k",
    )
    params = sent["params"]
    assert params["diet"] == "vegan"
    assert params["intolerances"] == "dairy,peanut"
    assert params["excludeIngredients"] == "cilantro"


def test_unset_filters_are_not_sent(sent):
    retrieval.complex_search(["avocado"], api_key="k")
    for absent in ("cuisine", "diet", "intolerances", "excludeCuisine", "type", "offset"):
        assert absent not in sent["params"]


def test_nutrition_is_opt_in_because_it_costs_quota(sent):
    retrieval.complex_search(["avocado"], api_key="k")
    assert "addRecipeNutrition" not in sent["params"]

    retrieval.complex_search(["avocado"], add_nutrition=True, api_key="k")
    assert sent["params"]["addRecipeNutrition"] is True


def test_ingredient_list_is_truncated(sent):
    retrieval.complex_search([f"i{n}" for n in range(120)], max_ingredients=3, api_key="k")
    assert sent["params"]["includeIngredients"] == "i0,i1,i2"


def test_number_is_capped_at_the_page_limit(sent):
    retrieval.complex_search(["avocado"], number=500, api_key="k")
    assert sent["params"]["number"] == retrieval.MAX_RECIPE_NUMBER


def test_results_are_unwrapped_from_the_envelope(sent):
    sent["payload"] = {"results": [{"id": 1}, {"id": 2}], "totalResults": 87}
    assert retrieval.complex_search(["avocado"], api_key="k") == [{"id": 1}, {"id": 2}]


def test_find_by_ingredients_returns_the_bare_list(sent):
    sent["payload"] = [{"id": 1}]
    assert retrieval.find_by_ingredients(["avocado"], api_key="k") == [{"id": 1}]
    assert sent["url"] == retrieval.FIND_BY_INGREDIENTS_URL


def test_quota_exhaustion_is_named(monkeypatch):
    monkeypatch.setattr(
        retrieval.requests, "get",
        lambda *a, **kw: FakeResponse({"message": "quota"}, status_code=402),
    )
    with pytest.raises(RuntimeError, match="quota"):
        retrieval.complex_search(["avocado"], api_key="k")


def test_missing_key_is_named(monkeypatch):
    monkeypatch.setattr(retrieval, "spoonacular_api_key", lambda: None)
    with pytest.raises(RuntimeError, match="SPOONACULAR_API_KEY"):
        retrieval.complex_search(["avocado"])
