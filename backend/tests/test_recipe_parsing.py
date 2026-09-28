"""Spoonacular recipe JSON -> Recipe contracts (matching/index.py)."""

import json

from cheaprecipe.matching import index


def line(name, amount, unit):
    return {
        "name": name,
        "aisle": "Produce",
        "measures": {"metric": {"amount": amount, "unitShort": unit}},
    }


def spoonacular(title, lines, dish_types=("main course",), ready=45, prep=None, cook=None):
    return {
        "id": abs(hash(title)) % 10_000,
        "title": title,
        "servings": 2,
        "readyInMinutes": ready,
        "preparationMinutes": prep,
        "cookingMinutes": cook,
        "cuisines": ["Thai", "Asian", "Martian"],
        "dishTypes": list(dish_types),
        "extendedIngredients": lines,
        "usedIngredients": [],
    }


def test_metric_units_map_to_ours():
    assert index.metric_quantity(line("x", 200, "g")).unit == "g"
    ml = index.metric_quantity(line("x", 250, "ml"))
    assert (ml.amount, ml.unit) == (0.25, "l")
    spoon = index.metric_quantity(line("x", 2, "Tbsps"))
    assert (spoon.amount, spoon.unit) == (0.03, "l")
    assert index.metric_quantity(line("egg", 2, "")).unit == "Stück"
    assert index.metric_quantity(line("garlic", 3, "cloves")).unit == "Stück"
    assert index.metric_quantity(line("rice", 1, "serving")) is None


def test_meals_only():
    assert index.is_meal({"dishTypes": ["lunch", "side dish"]})
    assert not index.is_meal({"dishTypes": ["dessert"]})
    assert not index.is_meal({"dishTypes": ["side dish", "salad"]})
    assert index.is_meal({"dishTypes": []})  # unknown: kept


def test_times_prefer_spoonacular_split():
    assert index.recipe_times({"readyInMinutes": 45, "preparationMinutes": 10, "cookingMinutes": 25}) == (10, 25)
    assert index.recipe_times({"readyInMinutes": 45, "preparationMinutes": None, "cookingMinutes": None}) == (None, 45)
    assert index.recipe_times({"readyInMinutes": 30, "preparationMinutes": -1, "cookingMinutes": -1}) == (None, 30)


def test_parse_recipe_json_skips_non_meals_and_unpriceable(tmp_path):
    path = tmp_path / "recipes.json"
    path.write_text(json.dumps([
        spoonacular("Curry", [line("onion", 150, "g"), line("salt", 1, "pinch")], prep=10, cook=30),
        spoonacular("Cookies", [line("flour", 200, "g")], dish_types=["dessert"]),
        spoonacular("Sushi", [line("tuna", 1, "serving")]),
    ]))
    [curry] = index.parse_recipe_json(str(path))
    assert curry.name == "Curry"
    assert [i.name for i in curry.ingredients] == ["onion"]
    assert (curry.preparation_time, curry.cooking_time) == (10, 30)
    assert curry.cuisine == ["Thai", "Asian"]
    assert curry.source == "spoonacular"

    assert len(index.parse_recipe_json(str(path), meals_only=False)) == 2
