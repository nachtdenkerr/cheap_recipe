"""Deterministic nutrition totals per recipe and per serving."""

from cheaprecipe.agents.contracts import Recipe


# TODO: scrape from EDEKA website? or retrieve from the Open Food Facts
def compute(recipe: Recipe) -> Recipe:
    raise NotImplementedError
