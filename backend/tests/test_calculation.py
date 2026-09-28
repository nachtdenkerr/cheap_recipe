"""Deterministic tests — assert on calculation/, no LLM calls."""

from types import SimpleNamespace

import pytest
from cheaprecipe.agents import planner
from cheaprecipe.agents.contracts import Ingredient, Item, Quantity, Recipe
from cheaprecipe.agents.planner import Basket, PlanningContext, build_planner
from cheaprecipe.calculation import cost, waste
from cheaprecipe.matching.offers import match_offer


def item(name, amount, unit, price, ppu=None, ppu_unit=None, offer_id=None):
    """An offer: a pack of `amount` `unit` for `price` euros."""
    ppu_unit = ppu_unit or ("kg" if unit == "g" else unit)
    if ppu is None:
        per = cost.convert(amount, unit, ppu_unit)
        ppu = price / per
    return Item(
        name=name,
        quantity=Quantity(amount=amount, unit=unit),
        price=price,
        price_per_unit=ppu,
        price_per_unit_unit=ppu_unit,
        offer_id=offer_id,
    )


def recipe(name, *lines, servings=2, minutes=30):
    return Recipe(
        name=name,
        ingredients=[
            Ingredient(name=n, quantity=Quantity(amount=a, unit=u)) for n, a, u in lines
        ],
        servings=servings,
        cooking_time=minutes,
        cuisine=[],
    )


ONIONS = item("onions", 500, "g", 1.00, offer_id=1)  # 1 €/500 g
BUTTER = item("butter", 250, "g", 1.79, offer_id=2)
EGGS = item("eggs", 10, "Stück", 2.50, offer_id=3)
PUMPKIN = item("hokkaido pumpkin", 1, "kg", 1.11, offer_id=4)


# --- units and prices ------------------------------------------------------

def test_convert_within_a_family():
    assert cost.convert(1500, "g", "kg") == 1.5
    assert cost.convert(0.25, "kg", "g") == 250
    assert cost.convert(3, "Stück", "Stück") == 3


@pytest.mark.parametrize("pair", [("g", "l"), ("Stück", "g"), ("kg", "Stück")])
def test_convert_refuses_to_guess(pair):
    with pytest.raises(cost.UnconvertibleUnit):
        cost.convert(1, *pair)


def test_price_of_uses_the_price_per_unit():
    assert cost.price_of(Quantity(amount=200, unit="g"), ONIONS) == pytest.approx(0.40)


def test_price_of_falls_back_to_the_pack_when_ppu_is_in_another_unit():
    # Eggs counted per piece but priced per kg on the shelf label.
    eggs = item("eggs", 10, "Stück", 2.50, ppu=4.0, ppu_unit="kg")
    assert cost.price_of(Quantity(amount=4, unit="Stück"), eggs) == pytest.approx(1.00)


def test_units_needed_rounds_up_but_not_float_noise():
    assert cost.units_needed(Quantity(amount=300, unit="g"), ONIONS) == 1
    assert cost.units_needed(Quantity(amount=501, unit="g"), ONIONS) == 2
    assert cost.units_needed(Quantity(amount=1, unit="kg"), ONIONS) == 2
    tenth = item("stock", 0.1, "l", 0.5)
    assert cost.units_needed(Quantity(amount=0.1 + 0.2, unit="l"), tenth) == 3
    assert cost.units_needed(Quantity(amount=0, unit="g"), ONIONS) == 0


def test_leftover_value_is_the_unused_share_of_the_pack():
    assert waste.leftover(500, 200) == 300
    assert waste.leftover(200, 500) == 0
    assert waste.leftover_value(500, 200, ONIONS) == pytest.approx(0.60)


# --- matching ----------------------------------------------------------------

def test_matching_accepts_a_more_specific_offer_and_plurals():
    offers = [PUMPKIN, EGGS, ONIONS]
    assert match_offer("pumpkin", offers) is PUMPKIN
    assert match_offer("egg", offers) is EGGS
    assert match_offer("Fresh Onion", offers) is ONIONS


def test_matching_never_accepts_a_less_specific_offer():
    assert match_offer("peanut butter", [BUTTER]) is None


def test_matching_needs_the_same_kind_of_thing():
    # From the dry run on real offers: the word is there, the product is not.
    bread = item("onion bread", 500, "g", 1.99)
    sausages = item("pepper sausages", 300, "g", 2.49)
    assert match_offer("onion", [bread]) is None
    assert match_offer("pepper", [sausages]) is None
    # A cut is still the same product.
    fillets = item("fresh chicken breast fillets", 100, "g", 1.29)
    assert match_offer("chicken breasts", [fillets]) is fillets


def test_matching_prefers_the_tightest_then_cheapest():
    plain = item("tomatoes", 500, "g", 1.49, offer_id=10)
    vine = item("vine tomatoes", 500, "g", 0.99, offer_id=11)
    cheap = item("tomatoes", 500, "g", 0.89, offer_id=12)
    assert match_offer("tomato", [vine, plain]) is plain
    assert match_offer("tomato", [plain, cheap]) is cheap


# --- whole recipes -------------------------------------------------------------

OMELETTE = recipe(
    "Onion omelette",
    ("egg", 4, "Stück"), ("onion", 200, "g"), ("butter", 20, "g"), ("salt", 1, "g"),
)


def test_compute_prices_packs_and_names_what_it_cannot_price():
    costing = cost.compute(OMELETTE, [ONIONS, BUTTER, EGGS])
    assert costing.total == pytest.approx(2.50 + 1.00 + 1.79)
    assert costing.used == pytest.approx(1.00 + 0.40 + 1.79 * 20 / 250)
    assert costing.per_serving == pytest.approx(costing.used / 2)
    assert costing.unpriced == ["salt"]


def test_two_lines_of_one_offer_are_summed_before_rounding():
    sauce = recipe("Sauce", ("onion", 300, "g"), ("onions", 300, "g"))
    assert cost.compute(sauce, [ONIONS]).total == pytest.approx(2.00)


def test_an_unconvertible_line_is_unpriced_not_guessed():
    soup = recipe("Soup", ("onion", 2, "Stück"))
    assert cost.compute(soup, [ONIONS]).unpriced == ["onion"]


def test_fridge_items_are_free_in_any_unit():
    fridge_eggs = item("eggs", 1, "kg", 0.0)
    costing = cost.compute(OMELETTE, [fridge_eggs, EGGS, ONIONS, BUTTER])
    assert costing.total == pytest.approx(1.00 + 1.79)  # no eggs bought
    assert "egg" not in costing.unpriced


def test_waste_compute_reports_each_pack():
    report = waste.compute(OMELETTE, [ONIONS, BUTTER, EGGS])
    onions = next(line for line in report["items"] if line["name"] == "onions")
    assert (onions["bought"], onions["used"], onions["leftover"]) == (500, 200, 300)
    assert report["leftover_value"] == pytest.approx(0.60 + 1.79 * 230 / 250 + 1.50)
    assert report["unpriced"] == ["salt"]


def test_cost_per_serving_counts_what_is_used():
    assert cost.cost_per_serving(OMELETTE, [ONIONS, BUTTER, EGGS]) == pytest.approx(
        (1.00 + 0.40 + 1.79 * 20 / 250) / 2
    )


# --- the basket ----------------------------------------------------------------

SOUP = recipe("Onion soup", ("onion", 300, "g"), ("butter", 30, "g"))


def test_a_second_recipe_uses_up_what_the_first_left():
    basket = Basket.from_offers([ONIONS, BUTTER, EGGS])
    assert basket.project(SOUP) == pytest.approx(
        (1.00 + 1.79, 0.40 + 1.79 * 220 / 250)
    )
    basket.commit(SOUP)

    # 200 g onions and 20 g butter are already paid for: only eggs are bought,
    # and the onion and butter leftovers shrink.
    extra_cost, extra_waste = basket.project(OMELETTE)
    assert extra_cost == pytest.approx(2.50)
    assert extra_waste == pytest.approx(1.50 - 0.40 - 1.79 * 20 / 250)


def test_project_does_not_mutate():
    basket = Basket.from_offers([ONIONS])
    basket.project(SOUP)
    assert basket.purchases == {}


def test_commit_buys_another_pack_only_for_the_shortfall():
    basket = Basket.from_offers([ONIONS])
    basket.commit(SOUP)  # 300 of 500 g
    basket.commit(recipe("More soup", ("onion", 400, "g")))  # 200 spare, 200 short
    [line] = basket.grocery_list()
    assert (line.quantity.amount, line.price) == (1000, pytest.approx(2.00))
    assert basket.leftovers()[0]["leftover"] == 300


def test_servings_scale_the_amounts():
    basket = Basket.from_offers([ONIONS])
    basket.commit(recipe("Soup for 4", ("onion", 300, "g"), servings=2), servings=4)
    assert basket.purchases["offer:1"].used == 600


def test_unpriced_ingredients_are_collected_once():
    basket = Basket.from_offers([ONIONS])
    basket.commit(OMELETTE)
    basket.commit(OMELETTE)
    assert basket.unpriced == ["egg", "butter", "salt"]


# --- the planner and its tools ---------------------------------------------------

def test_greedy_plan_prefers_recipes_that_share_packs():
    pumpkin_soup = recipe("Pumpkin soup", ("pumpkin", 500, "g"))
    pumpkin_gnocchi = recipe("Pumpkin gnocchi", ("pumpkin", 500, "g"))
    omelette = recipe("Plain omelette", ("egg", 10, "Stück"))
    result = planner.plan(
        [omelette, pumpkin_soup, pumpkin_gnocchi], [PUMPKIN, EGGS], number_of_meals=2
    )
    # One 1 kg pumpkin covers both: 1.11 € beats any plan with the eggs in it.
    assert sorted(r.name for r in result.recipes) == ["Pumpkin gnocchi", "Pumpkin soup"]
    assert result.total_cost == pytest.approx(1.11)
    assert [(i.name, i.quantity.amount) for i in result.grocery_list] == [("hokkaido pumpkin", 1)]


@pytest.fixture
def tools(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-not-used")
    build_planner.cache_clear()
    toolset = build_planner()._function_toolset.tools
    deps = PlanningContext(recipes=[SOUP, OMELETTE], offers=[ONIONS, BUTTER, EGGS], number_of_meals=2)
    ctx = SimpleNamespace(deps=deps)
    return {name: (lambda *a, _t=tool, **k: _t.function(ctx, *a, **k)) for name, tool in toolset.items()}


def test_price_recipe_tool(tools):
    result = tools["price_recipe"]("Onion soup")
    assert result == {
        "pack_cost_eur": 2.79,
        "used_cost_eur": round(0.60 + 1.79 * 30 / 250, 2),
        "per_serving_eur": round((0.60 + 1.79 * 30 / 250) / 2, 2),
        "unpriced": [],
    }


def test_estimate_leftovers_tool_accounts_for_sharing(tools):
    together = tools["estimate_leftovers"](["Onion soup", "Onion omelette"])
    apart = sum(
        tools["estimate_leftovers"]([name])["leftover_value_eur"]
        for name in ("Onion soup", "Onion omelette")
    )
    assert together["total_cost_eur"] == 1.00 + 1.79 + 2.50
    assert together["leftover_value_eur"] < apart
    assert together["unpriced"] == ["salt"]
