"""Allergens by ingredient name — deterministic, never delegated to the LLM.

The 14 allergens EU labels must declare (vocabulary.Allergen), found from the
words of an ingredient's name. Deliberately conservative: a word that usually
means an allergen counts ("flour" is wheat), and only named exceptions clear
it ("coconut milk" is not milk, "nutmeg" is not a nut, "eggplant" not an egg).
A false alarm hides a recipe from someone who could have eaten it; a miss
serves an allergen to someone who cannot — so the tables lean towards alarm.

Words are compared after the offer matcher's normalisation (singulars,
lower case; matching/offers.py), so "Walnuts" finds "walnut".
"""

from __future__ import annotations

from collections.abc import Iterable

from cheaprecipe.agents.contracts import Recipe
from cheaprecipe.matching.offers import PASTA_SHAPES, tokens

# allergen -> words (singular) that mean it
ALLERGEN_WORDS: dict[str, frozenset[str]] = {
    "gluten": frozenset({
        "wheat", "flour", "bread", "breadcrumb", "crumb", "panko", "pasta", "noodle",
        "couscous", "bulgur", "barley", "rye", "spelt", "semolina", "farro", "seitan",
        "cracker", "biscuit", "cake", "pastry", "dough", "tortilla", "pita", "baguette",
        "bun", "croissant", "beer", "orzo", "gnocchi", "dumpling", "wonton", "crouton",
        "oat",
    }) | PASTA_SHAPES,
    "crustaceans": frozenset({"shrimp", "prawn", "crab", "lobster", "crayfish", "langoustine", "krill"}),
    "eggs": frozenset({"egg", "mayonnaise", "mayo", "meringue", "aioli"}),
    "fish": frozenset({
        "fish", "salmon", "tuna", "cod", "pollock", "anchovy", "sardine", "trout",
        "herring", "perch", "mackerel", "haddock", "halibut", "tilapia", "sole", "bass",
        "carp", "pike", "monkfish", "swordfish", "catfish", "snapper", "worcestershire",
    }),
    "peanuts": frozenset({"peanut", "groundnut"}),
    "soy": frozenset({"soy", "soya", "tofu", "edamame", "miso", "tempeh", "tamari"}),
    "milk": frozenset({
        "milk", "butter", "cream", "cheese", "yogurt", "yoghurt", "parmesan", "parmigiano",
        "mozzarella", "ricotta", "mascarpone", "feta", "cheddar", "gruyere", "asiago",
        "pecorino", "brie", "camembert", "gouda", "emmental", "ghee", "buttermilk",
        "custard", "whey", "quark", "skyr", "kefir", "paneer", "halloumi",
    }),
    "nuts": frozenset({
        "nut", "almond", "hazelnut", "walnut", "cashew", "pecan", "pistachio", "macadamia",
    }),
    "celery": frozenset({"celery", "celeriac"}),
    "mustard": frozenset({"mustard"}),
    "sesame": frozenset({"sesame", "tahini"}),
    "sulphites": frozenset({"wine", "sulphite", "sulfite"}),
    "lupin": frozenset({"lupin", "lupine"}),
    "molluscs": frozenset({
        "mussel", "clam", "oyster", "squid", "octopus", "scallop", "calamari", "snail", "cockle",
    }),
}

# Phrases (all words present) that add an allergen the single words miss.
_ALSO: list[tuple[frozenset[str], str]] = [
    (frozenset({"soy", "sauce"}), "gluten"),  # brewed with wheat
    (frozenset({"egg", "noodle"}), "eggs"),
]

# Phrases (all words present) that clear an allergen a single word suggested.
_EXCEPT: list[tuple[frozenset[str], frozenset[str]]] = [
    (frozenset({"coconut", "milk"}), frozenset({"milk"})),
    (frozenset({"coconut", "cream"}), frozenset({"milk"})),
    (frozenset({"almond", "milk"}), frozenset({"milk"})),
    (frozenset({"oat", "milk"}), frozenset({"milk"})),
    (frozenset({"soy", "milk"}), frozenset({"milk"})),
    (frozenset({"rice", "milk"}), frozenset({"milk"})),
    (frozenset({"peanut", "butter"}), frozenset({"milk"})),
    (frozenset({"almond", "butter"}), frozenset({"milk"})),
    (frozenset({"cocoa", "butter"}), frozenset({"milk"})),
    (frozenset({"cream", "tartar"}), frozenset({"milk"})),
    (frozenset({"pasta", "sauce"}), frozenset({"gluten"})),  # the sauce, not the pasta
    (frozenset({"rice", "noodle"}), frozenset({"gluten"})),
    (frozenset({"rice", "flour"}), frozenset({"gluten"})),
    (frozenset({"corn", "flour"}), frozenset({"gluten"})),
    (frozenset({"almond", "flour"}), frozenset({"gluten"})),
    (frozenset({"coconut", "flour"}), frozenset({"gluten"})),
    (frozenset({"corn", "tortilla"}), frozenset({"gluten"})),
    (frozenset({"gluten", "free"}), frozenset({"gluten"})),
    (frozenset({"pine", "nut"}), frozenset({"nuts"})),  # a seed, not an EU tree nut
]


def allergens_of(name: str) -> set[str]:
    """The EU allergens an ingredient name points to."""
    words = tokens(name)
    found = {allergen for allergen, marks in ALLERGEN_WORDS.items() if words & marks}
    found |= {allergen for phrase, allergen in _ALSO if phrase <= words}
    for phrase, cleared in _EXCEPT:
        if phrase <= words:
            found -= cleared
    return found


def recipe_allergens(names: Iterable[str]) -> set[str]:
    return set().union(*(allergens_of(name) for name in names))


def filter_recipes(recipes: list[Recipe], excluded_allergens: set[str]) -> list[Recipe]:
    """The recipes with none of `excluded_allergens` in any ingredient."""
    excluded = {allergen.lower() for allergen in excluded_allergens}
    return [
        recipe
        for recipe in recipes
        if not excluded & recipe_allergens(i.name for i in recipe.ingredients)
    ]
