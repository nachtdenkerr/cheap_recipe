"""Recipe ingredient -> offer: which item on sale covers "carrots"?

Recipe ingredients arrive in Spoonacular's English ("chicken thighs", "egg"),
offers in normalization's ("fresh chicken thighs", "eggs"). Exact string
equality matched 3 of 51 on real data, so this compares word sets instead:

- words are lower-cased and singularised, and a few descriptors that never
  change what you buy ("fresh", "organic") are dropped;
- an offer matches when it contains every word of the ingredient — the offer
  may be more specific ("hokkaido pumpkin" covers "pumpkin"), never less
  ("butter" must not cover "peanut butter");
- and when both name the same thing: the last word, skipping cuts like
  "fillets", must agree. "onion bread" contains "onion" but is bread;
  "chicken breast fillets" is still chicken breast;
- of several matches, the tightest wins (fewest extra words), then the cheapest.

Deliberately conservative: a missed match leaves the ingredient unpriced,
which is visible; a wrong match prices the wrong thing, which is not.
"""

import re
from functools import lru_cache

from cheaprecipe.agents.contracts import Item

_WORD = re.compile(r"[a-zäöüß]+")

# Words that describe the state or quality of a product, not which product.
_DESCRIPTORS = frozenset({"fresh", "organic", "bio", "large", "small", "medium", "ripe"})

# How a product is cut or portioned, not what it is — skipped to find the head noun.
_CUTS = frozenset({"fillet", "piece", "slice", "cube", "chunk", "strip"})


def _singular(word: str) -> str:
    if len(word) <= 3:
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"  # berries -> berry
    if word.endswith("oes"):
        return word[:-2]  # tomatoes -> tomato
    if word.endswith(("ches", "shes", "xes", "sses")):
        return word[:-2]  # peaches -> peach
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]  # carrots -> carrot
    return word


@lru_cache(maxsize=4096)
def _words(name: str) -> tuple[str, ...]:
    return tuple(
        _singular(word) for word in _WORD.findall(name.lower()) if word not in _DESCRIPTORS
    )


@lru_cache(maxsize=4096)
def tokens(name: str) -> frozenset[str]:
    """The comparable words of a name. Cached: the planner asks for the same names often."""
    return frozenset(_words(name))


@lru_cache(maxsize=4096)
def head(name: str) -> str | None:
    """What the name is a kind of: its last word that is not a cut."""
    words = [word for word in _words(name) if word not in _CUTS]
    return words[-1] if words else None


def match_offer(ingredient: str, offers: list[Item]) -> Item | None:
    """The offer that covers `ingredient`, or None when none does."""
    wanted = tokens(ingredient)
    if not wanted:
        return None
    best: tuple[int, float, int] | None = None
    match: Item | None = None
    kind = head(ingredient)
    for position, offer in enumerate(offers):
        have = tokens(offer.name)
        if not wanted <= have or head(offer.name) != kind:
            continue
        # Position breaks exact ties, so the result is deterministic.
        rank = (len(have - wanted), offer.price, position)
        if best is None or rank < best:
            best, match = rank, offer
    return match
