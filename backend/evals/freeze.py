"""Freeze a branch's offers and the recipe pool, as they are now, into a fixture.

    uv run python -m evals.freeze --branch 10001604 --name edeka-frank

The recipes go in with what was learned about them — labels, course, edited
method — so a replay plans with the same pool the app had, without asking
Spoonacular or the labeller again.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from cheaprecipe.db.adapters import current_offers
from cheaprecipe.db.load import chain_of
from cheaprecipe.db.models import Address, RecipeCache
from cheaprecipe.db.session import make_engine
from cheaprecipe.refresh import week_start

FIXTURES = Path(__file__).with_name("fixtures")

OFFER_FIELDS = (
    "title", "price", "category", "description", "quantity_amount", "quantity_unit",
    "quantity_basis", "pack_count", "deposit", "price_per_unit", "price_per_unit_unit",
    "ingredient_en", "can_cook", "use_baking", "use_drinks", "meal_role", "base_ingredient",
)
RECIPE_FIELDS = (
    "source", "external_id", "name", "servings", "diet_type", "course", "dish_kind",
    "main_ingredient", "total_time", "cooking_time", "total_kcal", "instructions", "method_checked",
)
CANONICAL_FIELDS = ("name", "kcal_per_100", "protein_per_100", "carbs_per_100", "fat_per_100", "allergens")


def _json(value):
    return value.isoformat() if isinstance(value, date | datetime) else value


def freeze(session: Session, market_id: str) -> dict:
    branch = session.scalars(select(Address).where(Address.market_id == market_id)).one()
    offers = current_offers(session, [branch.id])
    recipes = list(session.scalars(select(RecipeCache)))
    canonicals = {o.canonical_ingredient for o in offers if o.canonical_ingredient}
    canonicals |= {line.canonical_ingredient for r in recipes for line in r.ingredients
                   if line.canonical_ingredient}
    return {
        "week_start": week_start().isoformat(),
        "frozen_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "branch": {"chain": chain_of(branch), "market_id": branch.market_id, "name": branch.name},
        "canonical_ingredients": [
            {f: getattr(c, f) for f in CANONICAL_FIELDS} for c in sorted(canonicals, key=lambda c: c.name)
        ],
        "offers": [
            {**{f: _json(getattr(o, f)) for f in OFFER_FIELDS},
             "valid_from": _json(o.valid_from), "valid_till": _json(o.valid_till),
             "canonical": o.canonical_ingredient.name if o.canonical_ingredient else None}
            for o in offers
        ],
        "recipes": [
            {**{f: getattr(r, f) for f in RECIPE_FIELDS},
             "cuisine": r.cuisine.name if r.cuisine else None,
             "lines": [{"name": line.name, "amount": line.amount, "unit": line.unit,
                        "canonical": line.canonical_ingredient.name if line.canonical_ingredient else None}
                       for line in r.ingredients]}
            for r in recipes
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--branch", required=True, help="the branch's market id, e.g. 10001604")
    parser.add_argument("--name", required=True, help="the fixture's name, e.g. edeka-frank")
    parser.add_argument("--database-url", help="default: DATABASE_URL, else data/cheaprecipe.db")
    args = parser.parse_args()
    with Session(make_engine(args.database_url)) as session:
        fixture = freeze(session, args.branch)
    FIXTURES.mkdir(exist_ok=True)
    path = FIXTURES / f"{args.name}.json"
    path.write_text(json.dumps(fixture, ensure_ascii=False, indent=1))
    print(f"{path}: {len(fixture['offers'])} offers, {len(fixture['recipes'])} recipes")


if __name__ == "__main__":
    main()
