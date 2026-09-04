"""Retrieve candidate recipes for the current offers and dump them to JSON.

Reads the classified CSV produced by scripts/fetch_edeka.py.

    uv run python scripts/load_recipes.py --diet normal --use cooking
"""

import argparse
import json
from pathlib import Path

import pandas as pd

from cheaprecipe.config import DATA_DIR
from cheaprecipe.matching import retrieval
from cheaprecipe.selection import select


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offers", type=Path, default=DATA_DIR / "new_columns.csv")
    parser.add_argument("--out", type=Path, default=DATA_DIR / "recipes.json")
    parser.add_argument("--diet", default="normal", choices=select.DIET_TYPES)
    parser.add_argument("--use", default="cooking", choices=tuple(select.USE_COLUMNS))
    parser.add_argument("--number", type=int, default=retrieval.DEFAULT_NUMBER)
    args = parser.parse_args()

    df = pd.read_csv(args.offers)
    selected = select.select_items(df, diet_type=args.diet, use=args.use)

    names = select.ingredient_names(selected, limit=retrieval.DEFAULT_MAX_INGREDIENTS)
    print(f"{len(selected)} offers selected; querying on: {', '.join(names)}")

    recipes = retrieval.find_by_ingredients(names, number=args.number)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(recipes, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(recipes)} recipes -> {args.out}")


if __name__ == "__main__":
    main()
