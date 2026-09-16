"""End-to-end pipeline: supermarket offers -> candidate recipes.

Two stages-of-stages, each runnable on its own:

    offers   fetch -> parse -> clean -> translate -> classify
    recipes  read classified CSV -> select -> retrieve

A CSV is written after every step so a failed or expensive LLM step can be
rerun against the checkpoint instead of re-fetching everything upstream.

    uv run cheaprecipe offers
    uv run cheaprecipe offers --store aldi
    uv run cheaprecipe offers --skip-llm      # deterministic steps only
    uv run cheaprecipe recipes --diet vegetarian --use cooking
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

from cheaprecipe import vocabulary
from cheaprecipe.config import DATA_DIR
from cheaprecipe.ingestion import aldi, edeka
from cheaprecipe.logging_setup import setup_logging, stage
from cheaprecipe.matching import retrieval
from cheaprecipe.normalization import classify, ingredients, normalize
from cheaprecipe.selection import select

log = logging.getLogger(__name__)

TRANSLATED_CSV = "translated.csv"
CLASSIFIED_CSV = "new_columns.csv"
RAW_CSV = "raw_offers.csv"
RECIPES_JSON = "recipes.json"

def _checkpoint(df: pd.DataFrame, path: Path) -> None:
    """Write a stage result and say where it went."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8")
    log.info("%d rows -> %s", len(df), path)


def _fetch_offers(store: vocabulary.Store, store_id: str | None) -> pd.DataFrame:
    """Run one chain's ingestion module and return its raw offers frame.

    Both modules expose the same fetch/parse pair over the same five columns;
    all that differs is what identifies the range — a market for EDEKA, a
    category for ALDI — so `store_id` carries whichever one applies.
    """
    if store == "edeka":
        module, identifier = edeka, store_id or edeka.DEFAULT_MARKET_ID
        payload = module.fetch_offers(market_id=identifier)
    else:
        module, identifier = aldi, store_id or aldi.DEFAULT_CATEGORY_ID
        payload = module.fetch_offers(category_id=identifier)

    log.debug("%s offers for id %s", store, identifier)
    return module.parse_offers(payload)


def build_offers(
    out_dir: Path = DATA_DIR,
    store: vocabulary.Store = "edeka",
    store_id: str | None = None,
    skip_llm: bool = False,
) -> pd.DataFrame:
    """Fetch the current offers and carry them through to classification.

    `store` selects the chain, and travels with the frame as far as
    `clean_offers`, which needs it to know that chain's non-food vocabulary.

    Returns the frame from the last step that ran — classified, or merely
    cleaned when skip_llm is set.
    """
    out_dir = Path(out_dir)

    with stage("fetch_offers", log, store=store, store_id=store_id):
        df = _fetch_offers(store, store_id)
        _checkpoint(df, out_dir / RAW_CSV)

    with stage("clean_offers", log, store=store):
        df = normalize.clean_offers(df, store)

    if skip_llm:
        log.info("--skip-llm: stopping after the deterministic steps")
        return df

    with stage("translate_ingredients", log):
        df = ingredients.add_ingredient_column(df, col_name="title")
        _checkpoint(df, out_dir / TRANSLATED_CSV)

    with stage("classify_ingredients", log):
        df = classify.add_classification_columns(df)
        _checkpoint(df, out_dir / CLASSIFIED_CSV)

    return df


def build_recipes(
    offers_path: Path | None = None,
    out_path: Path | None = None,
    diet_type: str = "normal",
    use: str = "cooking",
    number: int = retrieval.DEFAULT_RECIPE_NUMBER,
    cuisine: list[str] | None = None,
) -> list[dict]:
    """Select from the classified offers and retrieve candidate recipes."""
    offers_path = Path(offers_path or DATA_DIR / CLASSIFIED_CSV)
    out_path = Path(out_path or DATA_DIR / RECIPES_JSON)

    with stage("read_offers", log, path=str(offers_path)):
        if not offers_path.exists():
            raise FileNotFoundError(
                f"{offers_path} does not exist — run `cheaprecipe offers` first."
            )
        df = pd.read_csv(offers_path)
        log.info("read %d classified offers", len(df))

    with stage("select_items", log, use=use):
        selected = select.select_items(df, use=use)
        names = select.ingredient_names(
            selected, limit=retrieval.DEFAULT_MAX_INGREDIENTS
        )

    diet = vocabulary.spoonacular_diet(diet_type)

    with stage("retrieve_recipes", log, number=number, diet=diet):
        if diet or cuisine:
            # complexSearch is the only endpoint that filters by diet or
            # cuisine. Offers carry neither, so a preference that does not
            # reach this call is a preference that is silently ignored.
            recipes = retrieval.complex_search(
                names, number=number, cuisine=cuisine, diet=diet
            )
        else:
            recipes = retrieval.find_by_ingredients(names, number=number)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(recipes, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("%d recipes -> %s", len(recipes), out_path)

    return recipes


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cheaprecipe", description=__doc__)
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="DEBUG logging: per-batch LLM calls, token counts, HTTP detail",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    offers = subparsers.add_parser("offers", help="fetch, clean and classify offers")
    offers.add_argument("--out-dir", type=Path, default=DATA_DIR)
    offers.add_argument(
        "--store",
        default="edeka",
        choices=vocabulary.STORES,
        help="which chain to fetch from; also picks the non-food vocabulary "
             "applied when cleaning",
    )
    offers.add_argument(
        "--store-id",
        help="the range to fetch: EDEKA's market id (default "
             f"{edeka.DEFAULT_MARKET_ID}) or ALDI's category id (default "
             f"{aldi.DEFAULT_CATEGORY_ID})",
    )
    offers.add_argument(
        "--skip-llm",
        action="store_true",
        help="stop after the deterministic cleaning step",
    )

    recipes = subparsers.add_parser("recipes", help="retrieve recipes for the offers")
    recipes.add_argument("--offers", type=Path, default=DATA_DIR / CLASSIFIED_CSV)
    recipes.add_argument("--out", type=Path, default=DATA_DIR / RECIPES_JSON)
    recipes.add_argument(
        "--diet",
        default="normal",
        choices=vocabulary.DIET_TYPES,
        help="filters the recipes, not the offers; anything but 'normal' implies "
             "complexSearch",
    )
    recipes.add_argument("--use", default="cooking", choices=select.USE_CHOICES)
    recipes.add_argument("--number", type=int, default=retrieval.DEFAULT_RECIPE_NUMBER)
    recipes.add_argument(
        "--cuisine",
        action="append",
        choices=vocabulary.CUISINES,
        help="repeatable; implies complexSearch, the only endpoint that filters "
             "by cuisine (several cuisines go in one request, as OR)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    setup_logging("DEBUG" if args.verbose else "INFO")

    try:
        if args.command == "offers":
            build_offers(
                out_dir=args.out_dir,
                store=args.store,
                store_id=args.store_id,
                skip_llm=args.skip_llm,
            )
        else:
            build_recipes(
                offers_path=args.offers,
                out_path=args.out,
                diet_type=args.diet,
                use=args.use,
                number=args.number,
                cuisine=args.cuisine,
            )
    except Exception:  # noqa: BLE001 — the CLI boundary reports every failure
        # The failing stage already logged the traceback; exit non-zero without
        # printing it a second time.
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
