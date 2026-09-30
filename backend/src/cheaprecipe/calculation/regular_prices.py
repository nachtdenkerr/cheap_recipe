"""Typical regular prices, for ingredients that are not on offer this week.

Offers only price what is on sale. Everything else a recipe needs is bought
at the shelf price, which no data source here provides — so this table gives
a typical German supermarket price for the pack it is usually sold in. With
it, a recipe and a basket can be *estimated* ("≈ 12,40 €") instead of only
bounded from below ("from 8,90 €").

Deliberately approximate and short: the common ingredients that the dry run
showed missing most often. Numbers are regular (not discounted) prices for a
standard own-brand or mid-range pack, as of 2026; check them against a real
shelf from time to time. An ingredient that is not here stays unpriced — the
"from" floor — rather than getting a guess.

Entries are matched like offers are (matching/offers.py): the entry's words
must all appear in the ingredient's and name the same kind of thing, so
"red bell peppers" finds "bell pepper" and "ground beef" finds "ground beef",
but "beef broth" does not find "beef".

The estimated items flow through the same pack arithmetic as offers
(calculation/cost.py, the planner's Basket), so leftovers of a bunch of
parsley are valued exactly like leftovers of an offer pack.
"""

from __future__ import annotations

from cheaprecipe.agents.contracts import Item, Quantity
from cheaprecipe.calculation.weights import best_key
from cheaprecipe.vocabulary import Unit

# Shared entries, so related ingredients cannot drift apart.
_BEEF = (6.99, 0.5, "kg")  # stewing/roasting beef, about 14 EUR/kg
_GROUND_BEEF = (5.49, 0.5, "kg")
_DRIED_HERBS = (1.89, 0.015, "kg")  # a 15 g jar

# name -> (price in EUR, pack amount, pack unit)
REGULAR_PRICES: dict[str, tuple[float, float, Unit]] = {
    # vegetables
    "carrot": (1.29, 1, "kg"),
    "onion": (1.49, 1, "kg"),
    "red onion": (0.99, 0.5, "kg"),
    "shallot": (1.49, 0.25, "kg"),
    "spring onion": (0.79, 1, "Stück"),  # a bunch
    "scallion": (0.79, 1, "Stück"),
    "green onion": (0.79, 1, "Stück"),
    "leek": (0.99, 1, "Stück"),
    "potato": (2.49, 2.5, "kg"),
    "sweet potato": (2.99, 1, "kg"),
    "tomato": (2.49, 1, "kg"),
    "cherry tomato": (1.99, 0.25, "kg"),
    "cucumber": (0.79, 1, "Stück"),
    "zucchini": (2.49, 1, "kg"),
    "eggplant": (1.29, 1, "Stück"),
    "bell pepper": (0.99, 1, "Stück"),
    "cauliflower": (2.49, 1, "Stück"),
    "broccoli": (1.79, 0.5, "kg"),
    "savoy cabbage": (1.99, 1, "Stück"),
    "cabbage": (1.49, 1, "Stück"),
    "spinach": (1.99, 0.3, "kg"),
    "baby spinach": (1.99, 0.15, "kg"),
    "swiss chard": (2.49, 0.5, "kg"),
    "celery": (1.49, 1, "Stück"),
    "celery root": (1.99, 1, "Stück"),
    "mushroom": (1.99, 0.25, "kg"),
    "pumpkin": (2.49, 1, "Stück"),
    "lettuce": (1.19, 1, "Stück"),
    "avocado": (1.29, 1, "Stück"),
    "ginger": (1.49, 0.15, "kg"),
    # fruit
    "lemon": (0.59, 1, "Stück"),
    "lime": (0.49, 1, "Stück"),
    "apple": (2.49, 1, "kg"),
    "orange": (2.49, 1, "kg"),
    "banana": (1.69, 1, "kg"),
    # fresh herbs — sold as a bunch or pot
    "parsley": (1.29, 1, "Stück"),
    "basil": (1.99, 1, "Stück"),
    "cilantro": (1.29, 1, "Stück"),
    "coriander": (1.29, 1, "Stück"),
    "dill": (1.29, 1, "Stück"),
    "chive": (1.29, 1, "Stück"),
    "thyme": (1.49, 1, "Stück"),
    "rosemary": (1.49, 1, "Stück"),
    "sage": (1.49, 1, "Stück"),
    "mint": (1.49, 1, "Stück"),
    # meat and fish
    "beef": _BEEF,
    "chuck": _BEEF,  # a beef cut: priced as beef, minced or not
    "ground beef": _GROUND_BEEF,
    "ground veal": _GROUND_BEEF,  # rarely sold on its own; priced as beef mince
    "ground pork": (4.49, 0.5, "kg"),
    "chicken breast": (6.99, 0.6, "kg"),
    "chicken thigh": (5.99, 1, "kg"),
    "bacon": (2.29, 0.2, "kg"),
    "pork chop": (4.99, 0.5, "kg"),
    "pancetta": (2.99, 0.125, "kg"),
    "salmon": (5.99, 0.25, "kg"),
    # dairy and eggs
    "egg": (2.99, 10, "Stück"),
    "milk": (1.19, 1, "l"),
    "butter": (2.39, 0.25, "kg"),
    "cream": (1.19, 0.2, "l"),
    "sour cream": (0.99, 0.2, "kg"),
    "yogurt": (1.29, 0.5, "kg"),
    "cream cheese": (1.49, 0.2, "kg"),
    "parmesan": (3.49, 0.15, "kg"),
    "parmesan cheese": (3.49, 0.15, "kg"),
    "mozzarella": (1.19, 0.125, "kg"),
    "cheese": (2.49, 0.2, "kg"),
    "feta": (1.79, 0.2, "kg"),
    # dry goods and cans
    "pasta": (1.29, 0.5, "kg"),
    "rice": (1.99, 1, "kg"),
    "flour": (0.99, 1, "kg"),
    "bread crumb": (1.29, 0.4, "kg"),
    "lentil": (1.99, 0.5, "kg"),
    "chickpea": (1.29, 0.4, "kg"),
    "coconut milk": (1.79, 0.4, "l"),
    "tomato paste": (0.99, 0.2, "kg"),
    "tomato puree": (0.99, 0.5, "kg"),
    "pasta sauce": (2.29, 0.5, "kg"),
    "canned tomato": (1.19, 0.4, "kg"),
    "stock": (1.79, 1, "l"),
    "broth": (1.79, 1, "l"),
    "soy sauce": (2.49, 0.25, "l"),
    "honey": (4.49, 0.5, "kg"),
    "wine": (3.99, 0.75, "l"),
    "tortilla": (1.99, 8, "Stück"),
    # dried herbs — a jar, whatever the herb
    **{name: _DRIED_HERBS for name in (
        "oregano", "marjoram", "bay leaf", "italian seasoning", "herbes de provence",
        "dried thyme", "dried basil", "dried parsley", "dried rosemary", "dried sage",
        "dried dill", "dried mint", "dried oregano", "dried marjoram", "dried chive",
    )},
}

_PER_UNIT: dict[str, tuple[float, Unit]] = {
    # pack unit -> (factor to the price-per-unit unit, that unit)
    "g": (0.001, "kg"),
    "kg": (1.0, "kg"),
    "l": (1.0, "l"),
    "Stück": (1.0, "Stück"),
}


def regular_item(ingredient: str) -> Item | None:
    """An estimated shelf-price Item for `ingredient`, or None when unknown."""
    key = best_key(REGULAR_PRICES, ingredient)
    if key is None:
        return None
    price, amount, unit = REGULAR_PRICES[key]
    factor, ppu_unit = _PER_UNIT[unit]
    return Item(
        name=key,
        quantity=Quantity(amount=amount, unit=unit),
        price=price,
        price_per_unit=price / (amount * factor),
        price_per_unit_unit=ppu_unit,
        estimated=True,
    )

