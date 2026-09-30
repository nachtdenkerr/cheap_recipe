"""Deterministic tests — assert on calculation/, no LLM calls."""

from types import SimpleNamespace

import pytest
from cheaprecipe.agents import planner
from cheaprecipe.agents.contracts import Ingredient, Item, Quantity, Recipe
from cheaprecipe.agents.planner import Basket, PlanningContext, build_planner
from cheaprecipe.calculation import allergens as allergen_words
from cheaprecipe.calculation import cost, diet, pantry, regular_prices, waste
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
    ("egg", 4, "Stück"), ("onion", 200, "g"), ("butter", 20, "g"), ("saffron", 1, "g"),
)


def test_compute_prices_packs_and_names_what_it_cannot_price():
    costing = cost.compute(OMELETTE, [ONIONS, BUTTER, EGGS])
    assert costing.total == pytest.approx(2.50 + 1.00 + 1.79)
    assert costing.used == pytest.approx(1.00 + 0.40 + 1.79 * 20 / 250)
    assert costing.per_serving == pytest.approx(costing.used / 2)
    assert costing.unpriced == ["saffron"]


def test_two_lines_of_one_offer_are_summed_before_rounding():
    sauce = recipe("Sauce", ("onion", 300, "g"), ("onions", 300, "g"))
    assert cost.compute(sauce, [ONIONS]).total == pytest.approx(2.00)


def test_an_unconvertible_line_is_unpriced_not_guessed():
    # No typical weight for a "piece" of fennel seed: unpriced, not guessed.
    seeds = item("fennel seeds", 100, "g", 1.49)
    soup = recipe("Soup", ("fennel seeds", 2, "Stück"))
    assert cost.compute(soup, [seeds]).unpriced == ["fennel seeds"]


# --- typical weights -------------------------------------------------------------

def test_pieces_convert_through_typical_weights():
    assert cost.convert_ingredient(2, "Stück", "kg", "onion") == pytest.approx(0.3)
    assert cost.convert_ingredient(1, "Stück", "g", "chicken breasts") == 180
    assert cost.convert_ingredient(1400, "g", "Stück", "cauliflower") == pytest.approx(2)


def test_spoons_convert_through_density():
    # 2 Tbsp butter is 30 ml.
    assert cost.convert_ingredient(0.03, "l", "g", "unsalted butter") == pytest.approx(27.3)


def test_the_offer_name_is_the_fallback():
    # "red ones" says nothing; the offer it matched does.
    assert cost.convert_ingredient(1, "Stück", "g", "red ones", "red onion") == 150


def test_weights_need_the_same_kind_of_thing():
    with pytest.raises(cost.UnconvertibleUnit):
        cost.convert_ingredient(1, "Stück", "g", "pepper")  # black pepper, not bell
    assert cost.convert_ingredient(1, "Stück", "g", "red bell peppers") == 160


def test_one_onion_is_now_priced_against_a_bag():
    bag = item("onion", 2, "kg", 1.59, offer_id=20)
    soup = recipe("Soup", ("onion", 2, "Stück"))
    costing = cost.compute(soup, [bag])
    assert costing.unpriced == []
    assert costing.total == pytest.approx(1.59)
    assert costing.used == pytest.approx(1.59 * 0.3 / 2)


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
    assert report["unpriced"] == ["saffron"]


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
    # The soup's butter is not on offer here, so it is bought at the regular price.
    line = next(item for item in basket.grocery_list() if item.name == "onions")
    assert (line.quantity.amount, line.price) == (1000, pytest.approx(2.00))
    onions = next(left for left in basket.leftovers() if left["name"] == "onions")
    assert onions["leftover"] == 300


def test_servings_scale_the_amounts():
    basket = Basket.from_offers([ONIONS])
    basket.commit(recipe("Soup for 4", ("onion", 300, "g"), servings=2), servings=4)
    assert basket.purchases["offer:1"].used == 600


def test_unpriced_ingredients_are_collected_once():
    basket = Basket.from_offers([ONIONS])
    basket.commit(OMELETTE)
    basket.commit(OMELETTE)
    # Egg and butter get a regular-price estimate; only saffron has no price at all.
    assert basket.unpriced == ["saffron"]


# --- the planner and its tools ---------------------------------------------------

def test_greedy_plan_prefers_recipes_that_share_packs():
    pumpkin_soup = recipe("Pumpkin soup", ("pumpkin", 500, "g"))
    pumpkin_gnocchi = recipe("Pumpkin gnocchi", ("pumpkin", 500, "g"))
    omelette = recipe("Plain omelette", ("egg", 10, "Stück"))
    result = planner.plan(
        [omelette, pumpkin_soup, pumpkin_gnocchi], [PUMPKIN, EGGS], number_of_meals=2,
        min_offers=1,
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
        "estimated_eur": 0.0,
        "estimated": [],
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
    assert together["unpriced"] == ["saffron"]


# --- must use an offer --------------------------------------------------------

def test_offer_share_counts_offers_and_fridge_items():
    fridge_eggs = item("eggs", 1, "kg", 0.0)
    assert cost.offer_share(OMELETTE, [ONIONS, BUTTER, EGGS]) == 3 / 4  # saffron unpriced
    assert cost.offer_share(OMELETTE, []) == 0
    assert cost.offer_share(recipe("Eggs", ("egg", 2, "Stück")), [fridge_eggs]) == 1


def test_a_recipe_with_nothing_on_offer_is_never_planned():
    # Without the rule it would win: its cost is 0 because nothing is priced.
    nothing_on_sale = recipe("Saffron risotto", ("saffron", 1, "g"), ("arborio rice", 300, "g"))
    result = planner.plan([nothing_on_sale, SOUP], [ONIONS, BUTTER], number_of_meals=2, min_offers=1)
    assert [r.name for r in result.recipes] == ["Onion soup"]


def test_a_fridge_only_recipe_is_still_a_candidate():
    fridge_eggs = item("eggs", 1, "kg", 0.0)
    omelette = recipe("Fridge omelette", ("egg", 3, "Stück"))
    assert planner.using_offers([omelette], [fridge_eggs], minimum=1) == [omelette]


def test_equal_scores_go_to_the_recipe_with_more_on_offer():
    # Both are free (fridge items only), so the score ties; the one whose
    # ingredients are all covered wins over the one with an unpriced line.
    fridge = [item("eggs", 1, "kg", 0.0), item("leek", 1, "kg", 0.0)]
    partly = recipe("Egg and saffron", ("egg", 2, "Stück"), ("saffron", 1, "g"))
    fully = recipe("Egg and leek", ("egg", 2, "Stück"), ("leek", 1, "Stück"))
    result = planner.plan([partly, fully], fridge, number_of_meals=1, min_offers=1)
    assert [r.name for r in result.recipes] == ["Egg and leek"]


# --- objective and minimum offers -------------------------------------------------

def test_min_offers_filters_on_covered_lines():
    two = recipe("Two", ("onion", 100, "g"), ("butter", 10, "g"), ("salt", 1, "g"))
    three = recipe("Three", ("onion", 100, "g"), ("butter", 10, "g"), ("egg", 2, "Stück"))
    offers = [ONIONS, BUTTER, EGGS]
    assert planner.using_offers([two, three], offers, minimum=3) == [three]
    assert planner.using_offers([two, three], offers, minimum=1) == [two, three]


def test_waste_objective_prefers_using_up_a_pack_over_a_cheaper_new_one():
    # After the soup, 200 g onions and 220 g butter are left over.
    # "Onion tart" is dearer but uses the leftovers; "Egg cup" is cheap but
    # opens a new pack of eggs and wastes most of it.
    tart = recipe("Onion tart", ("onion", 200, "g"), ("butter", 200, "g"), ("flour", 1000, "g"))
    flour = item("wheat flour", 1000, "g", 3.50, offer_id=30)
    egg_cup = recipe("Egg cup", ("egg", 1, "Stück"))
    offers = [ONIONS, BUTTER, EGGS, flour]

    by_cost = planner.plan([SOUP, tart, egg_cup], offers, 2, objective="cost", min_offers=1)
    by_waste = planner.plan([SOUP, tart, egg_cup], offers, 2, objective="waste", min_offers=1)

    assert {r.name for r in by_cost.recipes} == {"Onion soup", "Egg cup"}
    assert {r.name for r in by_waste.recipes} == {"Onion soup", "Onion tart"}
    assert by_waste.total_cost > by_cost.total_cost


def test_by_default_a_recipe_needs_three_ingredients_on_offer():
    assert planner.DEFAULT_MIN_OFFERS == 3
    three = recipe("Three", ("onion", 100, "g"), ("butter", 10, "g"), ("egg", 2, "Stück"))
    result = planner.plan([SOUP, three], [ONIONS, BUTTER, EGGS], number_of_meals=2)
    assert [r.name for r in result.recipes] == ["Three"]  # the soup has only two


# --- pantry staples ------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["salt", "kosher salt", "ground black pepper", "brown sugar", "extra virgin olive oil",
     "sunflower oil", "garlic cloves", "salt and pepper"],
)
def test_staples_are_pantry(name):
    assert pantry.is_pantry(name)


@pytest.mark.parametrize(
    "name", ["bell pepper", "sesame oil", "garlic powder", "cumin", "pepper flakes", "oregano"]
)
def test_everything_else_is_shopping(name):
    assert not pantry.is_pantry(name)


def test_pantry_is_free_and_does_not_count_towards_offers():
    olive_oil = item("extra virgin olive oil", 0.5, "l", 4.99, offer_id=40)
    dish = recipe(
        "Onion soup with oil and garlic",
        ("onion", 300, "g"), ("olive oil", 0.03, "l"), ("garlic", 2, "Stück"), ("saffron", 1, "g"),
    )
    need = cost.needs(dish, [ONIONS, olive_oil])
    assert need.pantry == ["olive oil", "garlic"]  # not bought, even though oil is on offer
    assert cost.compute(dish, [ONIONS, olive_oil]).total == pytest.approx(1.00)
    # Shopping is onion + saffron: 1 of 2 on offer, whatever the pantry holds.
    assert cost.offer_lines(dish, [ONIONS, olive_oil]) == 1
    assert cost.offer_share(dish, [ONIONS, olive_oil]) == 0.5


# --- synonyms -------------------------------------------------------------------------

def test_pasta_shapes_match_pasta():
    pasta = item("pasta", 500, "g", 0.99)
    assert match_offer("rigatoni", [pasta]) is pasta
    assert match_offer("pappardelle pasta", [pasta]) is pasta
    assert match_offer("spaghetti squash", [pasta]) is None


def test_sauce_yogurt_and_wine_synonyms():
    sauce = item("pasta sauce", 400, "g", 1.49)
    yogurt = item("yogurt", 500, "g", 0.89)
    wine = item("wine", 1, "l", 1.99)
    assert match_offer("spaghetti sauce", [sauce]) is sauce
    assert match_offer("tomato-based pasta sauce", [sauce]) is sauce
    assert match_offer("greek yogurt", [yogurt]) is yogurt
    assert match_offer("white wine", [wine]) is wine
    # A synonym only restates the ingredient; it does not loosen the match.
    assert match_offer("barbecue sauce", [sauce]) is None


# --- regular-price estimates ---------------------------------------------------------

def test_regular_prices_match_like_offers():
    assert regular_prices.regular_item("red bell peppers").name == "bell pepper"
    assert regular_prices.regular_item("beef broth").name == "broth"  # not beef
    assert regular_prices.regular_item("saffron") is None
    carrots = regular_prices.regular_item("carrots")
    assert carrots.estimated and carrots.offer_id is None
    assert (carrots.price, carrots.quantity.amount, carrots.quantity.unit) == (1.29, 1, "kg")


def test_a_line_without_an_offer_is_estimated_not_unpriced():
    dish = recipe("Carrot soup", ("carrot", 500, "g"), ("onion", 100, "g"), ("saffron", 1, "g"))
    need = cost.needs(dish, [ONIONS])
    assert need.estimated == ["carrot"]
    assert need.unpriced == ["saffron"]

    costing = cost.compute(dish, [ONIONS])
    assert costing.estimated == ["carrot"]
    # 1 kg bag of carrots at 1.29 + the onion pack at 1.00
    assert costing.total == pytest.approx(1.29 + 1.00)
    assert costing.estimated_used == pytest.approx(1.29 / 2)
    # An estimate is never an offer: only the onion counts towards coverage.
    assert cost.offer_lines(dish, [ONIONS]) == 1


def test_estimated_purchases_reach_the_grocery_list_flagged():
    dish = recipe("Carrot soup", ("carrot", 500, "g"), ("onion", 100, "g"))
    basket = Basket.from_offers([ONIONS])
    basket.commit(dish)
    lines = {item.name: item for item in basket.grocery_list()}
    assert lines["carrot"].estimated and lines["carrot"].price == pytest.approx(1.29)
    assert not lines["onions"].estimated


def test_a_regular_pack_shared_by_two_recipes_is_bought_once():
    soup = recipe("Carrot soup", ("carrot", 400, "g"), ("onion", 100, "g"), ("leek", 1, "Stück"))
    salad = recipe("Carrot salad", ("carrot", 300, "g"), ("onion", 50, "g"), ("apple", 1, "Stück"))
    basket = Basket.from_offers([ONIONS])
    basket.commit(soup)
    extra_cost, _ = basket.project(salad)
    # 700 g of carrots fit one 1 kg bag: the salad pays only for its apples.
    assert extra_cost == pytest.approx(2.49)


def test_water_is_pantry_but_not_every_water():
    assert pantry.is_pantry("water") and pantry.is_pantry("boiling water")
    assert not pantry.is_pantry("coconut water")


@pytest.mark.parametrize(
    ("name", "key", "price"),
    [
        ("oregano", "oregano", 1.89),
        ("dried thyme", "dried thyme", 1.89),
        ("bay leaves", "bay leaf", 1.89),
        ("thyme", "thyme", 1.49),  # on its own: a fresh bunch
        ("ground veal", "ground veal", 5.49),  # priced as beef mince
        ("ground chuck", "chuck", 6.99),  # priced as beef
    ],
)
def test_herbs_veal_and_chuck_have_regular_prices(name, key, price):
    found = regular_prices.regular_item(name)
    assert (found.name, found.price) == (key, price)


def test_leaves_and_sprigs_are_the_herb():
    # "sage leaves" is sage, not a kind of leaf.
    assert regular_prices.regular_item("sage leaves").name == "sage"
    assert regular_prices.regular_item("thyme sprigs").name == "thyme"


def test_a_teaspoon_of_dried_herbs_uses_a_jar():
    dish = recipe("Herbed rice", ("rice", 200, "g"), ("oregano", 0.005, "l"))
    costing = cost.compute(dish, [])
    assert costing.unpriced == []
    # One 15 g jar bought, about a gram used.
    assert costing.total == pytest.approx(1.99 + 1.89)


# --- diet and allergens by ingredient ---------------------------------------------------



def test_a_wrong_vegetarian_flag_loses_to_the_beef():
    soup = ["carrots", "ground beef", "onion", "lentils"]
    assert diet.recipe_diet(soup, {"vegetarian": True, "vegan": False}) == "normal"


@pytest.mark.parametrize(
    ("ingredients", "expected"),
    [
        (["pasta", "butter", "onion"], "vegetarian"),
        (["coconut milk", "chickpeas", "rice"], "vegan"),
        (["cod", "corn tortilla", "lime"], "pescetarian"),
        (["veggie sausage", "bun"], "vegan"),
        (["honey", "oats"], "vegetarian"),
        (["chicken broth", "rice"], "normal"),
    ],
)
def test_diet_from_ingredients(ingredients, expected):
    assert diet.recipe_diet(ingredients) == expected


def test_diets_rank():
    assert diet.fits("vegan", "vegetarian") and diet.fits("vegetarian", "pescetarian")
    assert not diet.fits("normal", "vegetarian") and not diet.fits("pescetarian", "vegetarian")
    assert diet.fits(None, None) and not diet.fits(None, "vegan")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("walnuts", {"nuts"}), ("nutmeg", set()), ("coconut milk", set()),
        ("peanut butter", {"peanuts"}), ("eggplant", set()), ("egg noodles", {"eggs", "gluten"}),
        ("soy sauce", {"soy", "gluten"}), ("rice noodles", set()), ("pasta sauce", set()),
        ("parmesan cheese", {"milk"}), ("fish sauce", {"fish"}), ("celery root", {"celery"}),
        ("mussels", {"molluscs"}), ("prawns", {"crustaceans"}), ("tahini", {"sesame"}),
    ],
)
def test_allergens_by_name(name, expected):
    assert allergen_words.allergens_of(name) == expected


def test_filter_recipes_drops_the_recipe_not_just_the_line():
    nutty = recipe("Nut loaf", ("walnut", 100, "g"), ("onion", 100, "g"))
    plain = recipe("Onion soup", ("onion", 300, "g"))
    assert allergen_words.filter_recipes([nutty, plain], {"nuts"}) == [plain]


def test_an_offer_matches_by_the_name_recipes_use_for_it():
    from cheaprecipe.matching.offers import match_offer

    steaks = item("marinated chicken steaks", 550, "g", 4.99).model_copy(update={"base": "chicken breast"})
    neck = item("marinated pork neck steak", 600, "g", 3.59).model_copy(update={"base": "pork shoulder"})
    offers = [steaks, neck]
    assert match_offer("boneless skinless chicken breasts", offers) is steaks
    assert match_offer("pork shoulder", offers) is neck
    # The product name still matches too, and the base does not widen the head noun.
    assert match_offer("pork steak", offers) is neck
    assert match_offer("chicken thighs", offers) is None
