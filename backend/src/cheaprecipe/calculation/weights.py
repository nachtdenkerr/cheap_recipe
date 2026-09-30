"""Typical weights, for the conversions no constant can make.

`cost.convert` refuses "1 onion" against a 2 kg bag, and rightly: how much an
onion weighs is a fact about onions, not about units. This is where those
facts live — a piece weight per ingredient, a density for what recipes
measure by the spoon — so that "1 onion" can be priced and a pack's leftover
valued.

Deliberately short and deliberately average: an onion is 150 g, not the one in
your hand. Numbers are typical supermarket sizes (German produce, where it
differs). An ingredient that is not here stays unconvertible, and so unpriced
— visible, rather than priced with a guess.

Keys are matched like offers are (matching/offers.py): the entry's words must
all appear in the ingredient's, and they must name the same kind of thing, so
"red bell peppers" finds "bell pepper" and "chicken breasts" finds
"chicken breast" — but "pepper" alone finds nothing.
"""

from __future__ import annotations

from collections.abc import Iterable

from cheaprecipe.matching.offers import head, tokens

# Grams per piece ("Stück").
PIECE_GRAMS: dict[str, float] = {
    "onion": 150,
    "red onion": 150,
    "shallot": 30,
    "spring onion": 15,
    "scallion": 15,
    "green onion": 15,
    "leek": 200,
    "garlic": 5,  # one clove — recipes count cloves
    "carrot": 70,
    "potato": 170,
    "sweet potato": 300,
    "tomato": 120,
    "cherry tomato": 15,
    "cucumber": 350,
    "zucchini": 250,
    "courgette": 250,
    "eggplant": 300,
    "aubergine": 300,
    "bell pepper": 160,
    "cauliflower": 700,
    "broccoli": 400,
    "savoy cabbage": 900,
    "cabbage": 1000,
    "fennel": 250,
    "celery root": 700,
    "pumpkin": 1200,
    "hokkaido pumpkin": 1200,
    "mushroom": 20,
    "avocado": 170,
    "apple": 180,
    "pear": 180,
    "banana": 120,
    "orange": 180,
    "lemon": 100,
    "lime": 60,
    "mango": 350,
    "egg": 60,
    "chicken breast": 180,
    "chicken thigh": 120,
    "pork chop": 200,
    "sausage": 100,
    "bacon": 25,  # a rasher — recipes count slices
    "bay leaf": 0.2,
    # fresh herbs: a supermarket bunch or pot
    "parsley": 30,
    "basil": 25,
    "cilantro": 30,
    "coriander": 30,
    "dill": 25,
    "chive": 25,
    "thyme": 15,
    "rosemary": 15,
    "sage": 15,
    "mint": 25,
    "baguette": 250,
    "tortilla": 40,
}

# Grams per millilitre, for what recipes measure in spoons and cups.
DENSITY: dict[str, float] = {
    "butter": 0.91,
    "cream": 1.0,
    "milk": 1.03,
    "yogurt": 1.03,
    "oil": 0.92,
    "honey": 1.42,
    "sugar": 0.85,
    "flour": 0.53,
    "rice": 0.85,
    "wine": 0.99,
    "water": 1.0,
    "stock": 1.0,
    "broth": 1.0,
    "tomato puree": 1.05,
    "tomato paste": 1.1,
    "cheese": 0.45,  # grated
    "parmesan": 0.45,  # grated
    "pasta sauce": 1.05,
    # dried herbs, crumbled — a teaspoon is about a gram
    "oregano": 0.2,
    "marjoram": 0.2,
    "italian seasoning": 0.2,
    "herbes de provence": 0.2,
    "dried thyme": 0.2,
    "dried basil": 0.2,
    "dried parsley": 0.2,
    "dried rosemary": 0.2,
    "dried sage": 0.2,
    "dried dill": 0.2,
    "dried mint": 0.2,
    "dried oregano": 0.2,
    "dried marjoram": 0.2,
    "dried chive": 0.2,
    # chopped fresh herbs, loosely packed
    "parsley": 0.25,
    "basil": 0.25,
    "cilantro": 0.25,
    "coriander": 0.25,
    "dill": 0.25,
    "chive": 0.25,
    "thyme": 0.25,
    "rosemary": 0.25,
    "sage": 0.25,
    "mint": 0.25,
}


def best_key(keys: Iterable[str], name: str) -> str | None:
    """The most specific key that names the same thing as `name`.

    Shared with calculation/regular_prices.py, so both tables match alike.
    """
    have = tokens(name)
    kind = head(name)
    best = None
    for key in keys:
        if (
            tokens(key) <= have
            and head(key) == kind
            and (best is None or len(tokens(key)) > len(tokens(best)))
        ):
            best = key
    return best


def _lookup(table: dict[str, float], name: str) -> float | None:
    key = best_key(table, name)
    return table[key] if key else None


def piece_grams(name: str) -> float | None:
    return _lookup(PIECE_GRAMS, name)


def density(name: str) -> float | None:
    """Grams per millilitre."""
    return _lookup(DENSITY, name)
