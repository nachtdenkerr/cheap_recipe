"""Ingredient families: what "I don't eat pork" rules out.

A user's black list holds words like "pork", and recipes do not say pork —
they say bacon, Italian sausage, prosciutto. Matching the word alone let all
of those through. A family names what belongs to it, as words: any of them
in an ingredient makes it a member, unless the ingredient names an animal
outside the family ("chicken sausage" is not pork, "turkey bacon" is not).

Deterministic, like diet.py, whose meat words these overlap with: a dislike
is a promise to the user, not a judgement call.
"""

from __future__ import annotations

from functools import lru_cache

from cheaprecipe.matching.offers import tokens

_ANIMALS = {
    "pork": {"pork", "pig", "ham", "bacon", "pancetta", "prosciutto", "guanciale", "speck",
             "chorizo", "salami", "pepperoni", "lard", "kasseler", "kielbasa", "bratwurst",
             "frankfurter", "hotdog", "sausage", "mortadella", "porchetta", "spareribs"},
    "beef": {"beef", "steak", "chuck", "sirloin", "brisket", "oxtail", "ribeye", "tenderloin",
             "bresaola", "pastrami", "corned"},
    "lamb": {"lamb", "mutton"},
    "veal": {"veal"},
    "chicken": {"chicken"},
    "turkey": {"turkey"},
    "duck": {"duck"},
    "fish": {"fish", "salmon", "tuna", "cod", "trout", "mackerel", "herring", "sardine",
             "anchovy", "tilapia", "haddock", "halibut", "pollock", "redfish", "carp", "sole"},
    "seafood": {"shrimp", "prawn", "crab", "lobster", "mussel", "clam", "oyster", "scallop",
                "squid", "calamari", "octopus", "crayfish"},
}

# Families that are several of the above.
FAMILIES: dict[str, set[str]] = {
    **{name: {name} for name in _ANIMALS},
    "poultry": {"chicken", "turkey", "duck"},
    "red meat": {"pork", "beef", "lamb", "veal"},
    "meat": {"pork", "beef", "lamb", "veal", "chicken", "turkey", "duck"},
    "seafood": {"seafood", "fish"},
}
# Singular forms of family names, as a black list may hold "sausages" or "fish".
_ALIASES = {"poultry": "poultry", "shellfish": "seafood", "prawns": "seafood"}

# Words that make an animal word not that animal.
_NOT_ANIMAL = frozenset({"vegetarian", "vegan", "veggie", "meatless", "plant", "tofu", "seitan"})
# Words of each animal that are shared cuts or products, not the animal itself:
# "sausage" and "steak" are pork or beef only when no other animal is named.
_SHARED = {"sausage", "steak", "salami", "bacon", "ham", "tenderloin", "frankfurter", "hotdog",
           "kielbasa", "chorizo", "pepperoni", "bratwurst"}


def _key(name: str) -> frozenset[str]:
    return tokens(name)  # "Red Meat", "red meats" and "meat red" alike


_BY_KEY = {_key(name): animals for name, animals in FAMILIES.items()}
_BY_KEY.update({_key(alias): FAMILIES[name] for alias, name in _ALIASES.items()})


@lru_cache(maxsize=128)
def family_of(disliked: str) -> frozenset[str] | None:
    """The animals a black-list word stands for, or None if it names no family."""
    animals = _BY_KEY.get(_key(disliked))
    return frozenset(animals) if animals else None


@lru_cache(maxsize=4096)
def animals_in(ingredient: str) -> frozenset[str]:
    """Which animals an ingredient is made of, by its words."""
    words = tokens(ingredient)
    if words & _NOT_ANIMAL:
        return frozenset()
    named = {animal for animal, members in _ANIMALS.items() if words & (members - _SHARED)}
    if named:
        return frozenset(named)  # "chicken sausage" is chicken, not pork
    return frozenset(animal for animal, members in _ANIMALS.items() if words & members)


def in_family(ingredient: str, disliked: str) -> bool:
    """Whether `ingredient` belongs to the family `disliked` names."""
    family = family_of(disliked)
    return bool(family) and bool(animals_in(ingredient) & family)


def members(disliked: str) -> list[str]:
    """The words of a family, for a recipe search's exclusions; [] if none."""
    family = family_of(disliked)
    if not family:
        return []
    return sorted({word for animal in family for word in _ANIMALS[animal]})
