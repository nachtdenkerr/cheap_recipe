"""Replay frozen weeks through the real planner and critic, and measure them.

    uv run python -m evals.freeze --branch 10001604 --name edeka-frank   # save this week
    uv run python -m evals.run                                         # every fixture × profile
    uv run python -m evals.run --fixture edeka-frank --profile no-pork

See evals/run.py for what is measured. Fixtures and results hold store
offers and Spoonacular recipes, so they stay local (gitignored).
"""
