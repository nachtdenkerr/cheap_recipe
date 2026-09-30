"""What every kitchen is assumed to have, so recipes are not judged by it.

A pantry line is neither bought nor priced: it costs nothing, and it counts
neither for nor against how much of a recipe is on offer — otherwise salt, oil
and garlic alone would carry any recipe over the planner's offer threshold.

Deliberately short. Spices and dried herbs are left out on purpose: there are
too many different ones to assume any particular one is at home.

A line is pantry when its words are one of these staples plus only words that
describe the same staple ("ground black pepper", "extra virgin olive oil",
"garlic cloves") — so "bell pepper" and "sesame oil" are not.
"""

from __future__ import annotations

from cheaprecipe.matching.offers import tokens

PANTRY_STAPLES: frozenset[str] = frozenset({"salt", "pepper", "sugar", "oil", "garlic", "water"})

# Words that may come with a staple without making it something else.
_STAPLE_MODIFIERS = frozenset({
    # salt, pepper
    "sea", "kosher", "table", "fine", "coarse", "flaky", "black", "white",
    "ground", "cracked", "freshly", "peppercorn",
    # sugar
    "granulated", "caster", "brown", "cane",
    # oil
    "olive", "extra", "virgin", "vegetable", "sunflower", "canola", "rapeseed",
    "neutral", "cooking",
    # garlic
    "clove", "minced", "crushed",
    # water
    "cold", "warm", "hot", "boiling", "lukewarm", "tap", "ice",
    # amounts Spoonacular leaves in the name
    "tsp", "tbsp", "pinch", "to", "taste", "and",
})


def is_pantry(ingredient: str) -> bool:
    words = tokens(ingredient)
    staples = words & PANTRY_STAPLES
    return bool(staples) and words - staples <= _STAPLE_MODIFIERS
