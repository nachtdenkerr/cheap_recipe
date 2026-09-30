"""What a disliked word rules out — calculation/families.py. No model."""

import pytest

from cheaprecipe.calculation.families import in_family, members
from cheaprecipe.refresh import excluded_ingredients


@pytest.mark.parametrize("ingredient", [
    "italian sausage", "bacon", "thick-cut bacon", "prosciutto", "pancetta", "ham",
    "chorizo sausage", "pork chops", "ground pork", "salami", "lard",
])
def test_pork_is_more_than_the_word(ingredient):
    assert in_family(ingredient, "pork")


@pytest.mark.parametrize("ingredient", [
    "chicken sausage", "turkey bacon", "beef steak", "vegetarian sausage", "onion", "hamburger buns",
])
def test_what_is_not_pork(ingredient):
    assert not in_family(ingredient, "pork")


def test_wider_and_other_families():
    assert in_family("shrimp", "seafood") and in_family("salmon fillet", "seafood")
    assert in_family("ground beef", "red meat") and in_family("chicken thighs", "meat")
    assert in_family("duck breast", "poultry") and not in_family("pork belly", "poultry")
    assert in_family("sausages", "Pork")  # the black list's own spelling
    assert not in_family("apple", "apple")  # not a family: is_kind_of decides


def test_a_search_excludes_the_whole_family():
    excluded = excluded_ingredients(("pork", "apple"))
    assert excluded[0] == "pork" and "bacon" in excluded and "sausage" in excluded
    assert excluded[-1] == "apple" and members("apple") == []
