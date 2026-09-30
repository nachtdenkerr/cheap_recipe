"""The users every frozen week is planned for — the cases that went wrong before.

Each is the preferences a user sets in the profile. Keep the names stable:
reports are compared by fixture and profile name.
"""

PROFILES: dict[str, dict] = {
    # The plain case: what most weeks look like.
    "everyday": {"diet_type": "normal", "household_size": 1, "meal_types": ["lunch", "dinner"]},
    # Dislikes by family: no bacon, sausage or ham either.
    "no-pork": {"diet_type": "normal", "household_size": 1, "meal_types": ["lunch", "dinner"],
                "black_list": ["pork"]},
    # A diet the pool is short of; the vegetarian bug of September.
    "vegetarian": {"diet_type": "vegetarian", "household_size": 1, "meal_types": ["lunch", "dinner"],
                   "black_list": ["apple"]},
    # Breakfast quotas, and a household the servings have to stretch to.
    "family-three-meals": {"diet_type": "normal", "household_size": 2,
                           "meal_types": ["breakfast", "lunch", "dinner"]},
    # An allergen and little time on weekdays.
    "busy-milk-allergy": {"diet_type": "normal", "household_size": 1, "meal_types": ["dinner"],
                          "allergens": ["milk"], "week_time_availability": [30, 30, 30, 30, 30, 90, 90]},
}
