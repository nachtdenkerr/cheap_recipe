"""Dry run of the planner on local data: saved recipes against saved offers.

    uv run python scripts/dry_run_plan.py                    # free: greedy plan only
    uv run python scripts/dry_run_plan.py --llm              # + planner agent and critic

Reads data/<store>_recipes.json (a Spoonacular search) and
data/<store>_offers_classified.csv (the offers after normalization), as
`cheaprecipe offers` and `cheaprecipe recipes` write them — so nothing is
fetched and no database is needed.
Both files are gitignored — which is why this is a script and not a test.

Without --llm it runs only the deterministic parts: matching, the greedy
planner, the time check. --llm runs agents/loop.py for real, which calls
OpenRouter (OPENROUTER_API_KEY from .env) and costs tokens.
"""

from __future__ import annotations

import argparse
import logging
import math
from pathlib import Path

import pandas as pd

from cheaprecipe.agents import critic, loop, planner
from cheaprecipe.agents.contracts import Item, Quantity, Recipe, UserPreference
from cheaprecipe.calculation import cost
from cheaprecipe.config import DATA_DIR
from cheaprecipe.matching.index import parse_recipe_json
from cheaprecipe.matching.offers import match_offer
from cheaprecipe.observability.tracing import setup_tracing
from cheaprecipe.pipeline import classified_offers_csv, recipes_json
from cheaprecipe.vocabulary import STORES

def load_offers(path: Path) -> tuple[list[Item], int]:
    """Cookable offers the planner can price; also how many were left out."""
    frame = pd.read_csv(path)
    items, skipped = [], 0
    for position, row in enumerate(frame.itertuples(index=False)):
        unit = cost.unit_of(row.quantity_unit)
        ppu_unit = cost.unit_of(row.price_per_unit_unit)
        usable = (
            row.can_cook is True
            and unit is not None
            and ppu_unit is not None
            and not math.isnan(row.quantity_amount)
            and not math.isnan(row.price_per_unit)
            and isinstance(row.ingredient_en, str)
        )
        if not usable:
            skipped += 1
            continue
        items.append(
            Item(
                name=row.ingredient_en,
                quantity=Quantity(amount=row.quantity_amount * unit[1], unit=unit[0]),
                price=row.price,
                price_per_unit=row.price_per_unit,
                price_per_unit_unit=ppu_unit[0],
                offer_id=position,
            )
        )
    return items, skipped


def matching_report(recipes: list[Recipe], offers: list[Item]) -> None:
    lines = [(r, i) for r in recipes for i in r.ingredients]
    matched = [(r, i, match_offer(i.name, offers)) for r, i in lines]
    hits = [(i.name, o.name) for _, i, o in matched if o is not None]
    print(f"\nMatching: {len(hits)} of {len(lines)} ingredient lines match an offer")
    for ingredient, offer in sorted(set(hits)):
        print(f"  {ingredient:28} -> {offer}")


def plan_report(title: str, plan, recipes: list[Recipe], offers: list[Item], pref) -> None:
    print(f"\n{title}")
    for recipe in plan.recipes:
        costing = cost.compute(recipe, offers)
        print(
            f"  - {recipe.name} ({critic.total_minutes(recipe)} min, serves {recipe.servings}): "
            f"{costing.total:.2f} EUR on its own"
        )
        if costing.estimated:
            print(f"      estimated at regular price: {', '.join(costing.estimated)}")
        if costing.unpriced:
            print(f"      no price at all: {', '.join(costing.unpriced)}")
    basket = planner.Basket.from_offers(offers)
    for recipe in plan.recipes:
        basket.commit(recipe)
    on_offer = sum(line.price for line in plan.grocery_list if not line.estimated)
    estimated = sum(line.price for line in plan.grocery_list if line.estimated)
    print(
        f"  Basket for the week: ≈ {plan.total_cost or 0:.2f} EUR "
        f"({on_offer:.2f} on offer + ≈ {estimated:.2f} at regular prices), "
        f"{basket.leftover_value:.2f} EUR left over in opened packs"
    )
    for line in sorted(plan.grocery_list, key=lambda item: item.estimated):
        mark = "≈" if line.estimated else " "
        print(
            f"    {mark} buy {line.quantity.amount:g} {line.quantity.unit} {line.name}: "
            f"{line.price:.2f} EUR{'  (regular price)' if line.estimated else ''}"
        )
    conflicts = critic.time_conflicts(plan, pref.week_time_availability)
    if pref.week_time_availability:
        print(f"  Does not fit the week: {', '.join(conflicts) or 'nothing'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--store", default="edeka", choices=STORES)
    parser.add_argument("--recipes", type=Path, help="default: data/<store>_recipes.json")
    parser.add_argument(
        "--offers", type=Path, help="default: data/<store>_offers_classified.csv"
    )
    parser.add_argument("--meals", type=int, default=5)
    parser.add_argument(
        "--week", help="minutes per day, Monday first, e.g. 30,30,45,30,60,90,60"
    )
    parser.add_argument("--notes", help='free text for the agents, e.g. "nothing spicy"')
    parser.add_argument("--objective", choices=["cost", "waste"], default=planner.DEFAULT_OBJECTIVE)
    parser.add_argument(
        "--min-offers", type=int, default=planner.DEFAULT_MIN_OFFERS,
        help="ingredient lines a recipe needs on offer to be planned",
    )
    parser.add_argument("--llm", action="store_true", help="run the planner agent + critic loop")
    parser.add_argument("--rounds", type=int, default=loop.MAX_ROUNDS)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.llm else logging.WARNING, format="%(message)s")
    if args.llm and setup_tracing():
        print("Tracing to Phoenix — open http://localhost:6006 to follow the agents.")

    recipes_path = args.recipes or DATA_DIR / recipes_json(args.store)
    offers_path = args.offers or DATA_DIR / classified_offers_csv(args.store)
    recipes = parse_recipe_json(str(recipes_path))
    offers, skipped = load_offers(offers_path)
    week = [int(m) for m in args.week.split(",")] if args.week else None
    pref = UserPreference(week_time_availability=week, notes=args.notes)
    print(f"{len(recipes)} recipes, {len(offers)} usable offers ({skipped} left out)")

    matching_report(recipes, offers)

    print(f"\nCandidates: {len(recipes)} meals parsed")
    if week:
        # What POST /generate does before planning: nothing longer than the freest day.
        recipes = [r for r in recipes if critic.total_minutes(r) <= max(week)]
        print(f"  {len(recipes)} fit the freest day ({max(week)} min)")
    counts = {id(r): cost.offer_lines(r, offers) for r in recipes}
    for minimum in (1, 2, 3, 4):
        left = sum(1 for n in counts.values() if n >= minimum)
        print(f"  {left:2} have {minimum}+ ingredients on offer")
    using = planner.using_offers(recipes, offers, args.min_offers)
    print(f"  -> planning from the {len(using)} with {args.min_offers}+:")
    for recipe in sorted(using, key=lambda r: -counts[id(r)]):
        shopping = len(recipe.ingredients) - len(cost.needs(recipe, offers).pantry)
        print(f"    {counts[id(recipe)]:2}/{shopping:2} of the shopping on offer  {recipe.name[:60]}")
    greedy = planner.plan(
        recipes, offers, args.meals, objective=args.objective, min_offers=args.min_offers
    )
    plan_report(
        f"Greedy plan ({args.objective} first, free, deterministic):",
        greedy, recipes, offers, pref,
    )

    if args.llm:
        result = loop.run(recipes, offers, args.meals, pref, max_rounds=args.rounds)
        plan_report(
            f"After the planner/critic loop ({result.rounds} round(s)):",
            result.plan, recipes, offers, pref,
        )
        verdict = result.critique
        print(f"  Critic: {'passed' if verdict.passed else 'not passed'}")
        for issue in verdict.issues:
            print(f"    issue: {issue}")
        for suggestion in verdict.suggestions:
            print(f"    suggestion: {suggestion}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
