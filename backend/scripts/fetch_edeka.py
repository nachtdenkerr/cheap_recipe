"""Fetch and normalize current EDEKA offers.

Mirrors workflow.ipynb: fetch -> parse -> clean -> ingredient_en -> classify.
Each stage is written out so a failed (or expensive) LLM stage can be rerun
against the CSV instead of re-fetching.

    uv run python scripts/fetch_edeka.py --out-dir data
"""

import argparse
from pathlib import Path

from cheaprecipe.config import DATA_DIR
from cheaprecipe.ingestion import edeka
from cheaprecipe.normalization import classify, ingredients, normalize


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--market-id", default=edeka.DEFAULT_MARKET_ID)
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="stop after the deterministic cleaning stage",
    )
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    json_data = edeka.fetch_offers(market_id=args.market_id)
    df = edeka.parse_offers(json_data)

    df = normalize.clean_offers(df)
    df.to_csv(args.out_dir / "offers_clean.csv", index=False, encoding="utf-8")
    print(f"{len(df)} offers -> {args.out_dir / 'offers_clean.csv'}")

    if args.skip_llm:
        return

    df = ingredients.add_ingredient_column(df, col_name="title")
    df.to_csv(args.out_dir / "translated.csv", index=False, encoding="utf-8")
    print(f"ingredients -> {args.out_dir / 'translated.csv'}")

    df = classify.add_classification_columns(df)
    df.to_csv(args.out_dir / "new_columns.csv", index=False, encoding="utf-8")
    print(f"classified -> {args.out_dir / 'new_columns.csv'}")


if __name__ == "__main__":
    main()
