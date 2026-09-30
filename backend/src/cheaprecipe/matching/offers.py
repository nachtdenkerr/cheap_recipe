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

Before comparing, an ingredient is restated in the words offers use:
"rigatoni" is sold as pasta, "spaghetti sauce" as pasta sauce, "greek
yogurt" as yogurt (`canonical`). Both tables are short on purpose; extend
them when a dry run shows a miss.

An offer is also known by its base ingredient — the plain name recipes use
for it ("chicken breast" for marinated chicken steaks, "pork shoulder" for
marinated neck steaks) — and matches by either name.

Deliberately conservative: a missed match leaves the ingredient unpriced,
which is visible; a wrong match prices the wrong thing, which is not.
"""

import re
from functools import lru_cache

from cheaprecipe.agents.contracts import Item

_WORD = re.compile(r"[a-zäöüß]+")

# Words that describe the state or quality of a product, not which product.
_DESCRIPTORS = frozenset({
    "fresh", "organic", "bio", "large", "small", "medium", "ripe", "boneless", "skinless",
})

# How a product is cut or portioned, not what it is — skipped to find the head noun.
_CUTS = frozenset({"fillet", "piece", "slice", "cube", "chunk", "strip", "leaf", "sprig"})

# Pasta shapes, which supermarkets sell as "pasta". Replaced only where the
# shape names the pasta itself — "rigatoni", "spaghetti sauce" — and not in
# "spaghetti squash", which is a squash.
PASTA_SHAPES = frozenset({
    "rigatoni", "penne", "spaghetti", "spaghettini", "linguine", "fettuccine",
    "fettucine", "tagliatelle", "pappardelle", "fusilli", "farfalle",
    "orecchiette", "macaroni", "conchiglie", "rotini", "ziti", "bucatini",
})
_PASTA_HEADS = frozenset({"pasta", "sauce"})

# Whole names -> the name offers use, compared as word sets after singulars.
SYNONYMS: dict[str, str] = {
    "tomato-based pasta sauce": "pasta sauce",
    "tomato pasta sauce": "pasta sauce",
    "marinara sauce": "pasta sauce",
    "marinara": "pasta sauce",
    "greek yogurt": "yogurt",
    "plain yogurt": "yogurt",
    "natural yogurt": "yogurt",
    "white wine": "wine",
    "dry white wine": "wine",
}


def _singular(word: str) -> str:
    if len(word) <= 3:
        return word
    if word == "leaves":
        return "leaf"  # not "leave"; -ves -> -f is too broad (olives, cloves)
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


@lru_cache(maxsize=1)
def _synonyms() -> dict[frozenset[str], str]:
    return {frozenset(_words(key)): value for key, value in SYNONYMS.items()}


@lru_cache(maxsize=4096)
def canonical(ingredient: str) -> str:
    """`ingredient` in the words offers use (see SYNONYMS, PASTA_SHAPES)."""
    words = _words(ingredient)
    replaced = _synonyms().get(frozenset(words))
    if replaced is not None:
        return replaced
    if words and (words[-1] in PASTA_SHAPES or words[-1] in _PASTA_HEADS):
        words = tuple("pasta" if w in PASTA_SHAPES else w for w in words)
        # "pappardelle pasta" -> "pasta pasta" -> "pasta"
        words = tuple(w for i, w in enumerate(words) if i == 0 or w != words[i - 1])
    return " ".join(words)


def is_kind_of(ingredient: str, kind: str) -> bool:
    """Whether `ingredient` is a `kind` — by the same rules offers match by.

    "granny smith apples" is an apple; "apple cider vinegar" is a vinegar,
    so it is not. Used for the ingredients a user does not eat.
    """
    ingredient, kind = canonical(ingredient), canonical(kind)
    wanted = tokens(kind)
    return bool(wanted) and wanted <= tokens(ingredient) and head(kind) == head(ingredient)


def match_offer(ingredient: str, offers: list[Item]) -> Item | None:
    """The offer that covers `ingredient`, or None when none does."""
    ingredient = canonical(ingredient)
    wanted = tokens(ingredient)
    if not wanted:
        return None
    best: tuple[bool, int, float, int] | None = None
    match: Item | None = None
    kind = head(ingredient)
    for position, offer in enumerate(offers):
        for by_base, name in ((False, offer.name), (True, offer.base)):
            if not name:
                continue
            have = tokens(name)
            if not wanted <= have or head(name) != kind:
                continue
            # The product's own name before its base: a recipe's "pork steak"
            # is the steak on offer, not whatever else is also "pork shoulder".
            # Position breaks exact ties, so the result is deterministic.
            rank = (by_base, len(have - wanted), offer.price, position)
            if best is None or rank < best:
                best, match = rank, offer
    return match
