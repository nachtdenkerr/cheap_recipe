"""End-to-end pipeline: supermarket offers -> candidate recipes.

Two stages-of-stages, each runnable on its own:

    offers   fetch -> parse -> clean -> translate -> classify
    recipes  read classified CSV -> select -> retrieve

A CSV is written after every step so a failed or expensive LLM step can be
rerun against the checkpoint instead of re-fetching everything upstream. Each
file is named for the store, what it holds and the stage that wrote it, so an
EDEKA run and an ALDI run never overwrite each other:

    data/edeka_offers_raw.csv          as fetched
    data/edeka_offers_translated.csv   + ingredient_en
    data/edeka_offers_classified.csv   + can_cook / use_baking / use_drinks
    data/edeka_recipes.json            Spoonacular recipes for those offers

    uv run cheaprecipe offers
    uv run cheaprecipe offers --store aldi
    uv run cheaprecipe offers --skip-llm      # deterministic steps only
    uv run cheaprecipe recipes --diet vegetarian --use cooking
    uv run cheaprecipe recipes --store aldi --cuisine Thai
    uv run cheaprecipe load                   # both files -> the API's database
    uv run cheaprecipe weekly                 # all of it, as the API does on Mondays
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



def _prefix(store: vocabulary.Store, store_id: str | None) -> str:
    """The files' prefix: the chain, and the branch unless it is the default one.

    Every branch a user shops at gets its offers fetched (refresh.py), and
    one file per chain would let the last branch fetched overwrite the one
    `cheaprecipe load` means.
    """
    default = edeka.DEFAULT_MARKET_ID if store == "edeka" else aldi.DEFAULT_CATEGORY_ID
    return store if store_id in (None, default) else f"{store}_{store_id}"


def raw_offers_csv(store: vocabulary.Store, store_id: str | None = None) -> str:
    """Offers as fetched, before any cleaning."""
    return f"{_prefix(store, store_id)}_offers_raw.csv"


def translated_offers_csv(store: vocabulary.Store, store_id: str | None = None) -> str:
    """Cleaned offers with their English ingredient name."""
    return f"{_prefix(store, store_id)}_offers_translated.csv"


def classified_offers_csv(store: vocabulary.Store, store_id: str | None = None) -> str:
    """Translated offers with the cooking/baking/drinks flags — the input to recipes."""
    return f"{_prefix(store, store_id)}_offers_classified.csv"


def recipes_json(store: vocabulary.Store) -> str:
    """Spoonacular's recipes for that store's classified offers."""
    return f"{store}_recipes.json"


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
        _checkpoint(df, out_dir / raw_offers_csv(store, store_id))

    with stage("clean_offers", log, store=store):
        df = normalize.clean_offers(df, store)

    if skip_llm:
        log.info("--skip-llm: stopping after the deterministic steps")
        return df

    with stage("translate_ingredients", log):
        df = ingredients.add_ingredient_column(df, col_name="title")
        _checkpoint(df, out_dir / translated_offers_csv(store, store_id))

    with stage("classify_ingredients", log):
        df = classify.add_classification_columns(df)
        _checkpoint(df, out_dir / classified_offers_csv(store, store_id))

    return df


def build_recipes(
    offers_path: Path | None = None,
    out_path: Path | None = None,
    store: vocabulary.Store = "edeka",
    diet_type: str = "normal",
    use: str = "cooking",
    number: int = retrieval.DEFAULT_RECIPE_NUMBER,
    cuisine: list[str] | None = None,
) -> list[dict]:
    """Select from the classified offers and retrieve candidate recipes."""
    offers_path = Path(offers_path or DATA_DIR / classified_offers_csv(store))
    out_path = Path(out_path or DATA_DIR / recipes_json(store))

    with stage("read_offers", log, path=str(offers_path)):
        if not offers_path.exists():
            raise FileNotFoundError(
                f"{offers_path} does not exist — run `cheaprecipe offers --store {store}` first."
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
            # cuisine, and it does so across Spoonacular's whole catalogue.
            # Offers carry neither, so a preference that does not reach this
            # call is a preference that is silently ignored.
            recipes = retrieval.complex_search(
                names, number=number, cuisine=cuisine, diet=diet
            )
        else:
            # findByIngredients returns only ids and the used/missed split;
            # informationBulk fills in what parsing needs.
            recipes = retrieval.with_information(
                retrieval.find_by_ingredients(names, number=number)
            )

    if not recipes:
        # Keep the last usable result rather than replacing it with nothing.
        log.warning("no recipes retrieved; %s left unchanged", out_path)
        return recipes

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(recipes, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("%d recipes -> %s", len(recipes), out_path)

    return recipes


def load(
    store: vocabulary.Store = "edeka",
    store_id: str | None = None,
    offers_path: Path | None = None,
    recipes_path: Path | None = None,
    database_url: str | None = None,
) -> None:
    """Load a store's classified offers and recipes into the API's database.

    The database is DATABASE_URL, or data/cheaprecipe.db by default — the one
    `uvicorn app.main:app` serves. Safe to re-run; see db/load.py.
    """
    # Imported here so the offers/recipes commands never touch the database.
    from sqlalchemy.orm import Session

    from cheaprecipe.db.load import load_files
    from cheaprecipe.db.session import init_db, make_engine

    store_id = store_id or (
        edeka.DEFAULT_MARKET_ID if store == "edeka" else aldi.DEFAULT_CATEGORY_ID
    )
    offers_path = Path(offers_path or DATA_DIR / classified_offers_csv(store, store_id))
    recipes_path = Path(recipes_path or DATA_DIR / recipes_json(store))
    engine = make_engine(database_url)

    with stage("load_database", log, store=store, store_id=store_id, db=str(engine.url)):
        if not offers_path.exists():
            raise FileNotFoundError(
                f"{offers_path} does not exist — run `cheaprecipe offers --store {store}` first."
            )
        init_db(engine)
        with Session(engine) as session:
            report = load_files(session, offers_path, recipes_path, store, store_id)
        log.info("%s", report)


def weekly(store: vocabulary.Store = "edeka", force: bool = False, database_url: str | None = None):
    """This week's offers and a recipe pool for every diet in use, into the database.

    What the API's scheduler runs on Mondays (app/scheduler.py), for running
    it by hand or from a cron: every branch some user has as a home market,
    or `store`'s default branch when nobody has one yet. Skips what is
    already current unless --force.
    """
    from sqlalchemy.orm import Session

    from cheaprecipe.db.load import chain_of
    from cheaprecipe.db.session import init_db, make_engine
    from cheaprecipe.refresh import markets_in_use, weekly_refresh

    engine = make_engine(database_url)
    with stage("weekly_refresh", log, store=store, force=force, db=str(engine.url)):
        init_db(engine)
        with Session(engine) as session:
            branches = [(chain_of(b), b.market_id) for b in markets_in_use(session)] or [(store, None)]
            for chain, market_id in branches:
                summary = weekly_refresh(session, chain, market_id, force=force)
                log.info("%s:%s %s", chain, market_id, summary.as_dict())


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

    loader = subparsers.add_parser(
        "load", help="load classified offers and recipes into the API's database"
    )
    loader.add_argument("--store", default="edeka", choices=vocabulary.STORES)
    loader.add_argument(
        "--store-id",
        help="the branch the offers are from (default: the one `offers` fetches)",
    )
    loader.add_argument(
        "--offers", type=Path, help="default: data/<store>_offers_classified.csv"
    )
    loader.add_argument("--recipes", type=Path, help="default: data/<store>_recipes.json")
    loader.add_argument(
        "--database-url", help="default: DATABASE_URL, else data/cheaprecipe.db"
    )

    weekly_parser = subparsers.add_parser(
        "weekly", help="refresh offers and the recipe pool for every diet in use"
    )
    weekly_parser.add_argument("--store", default="edeka", choices=vocabulary.STORES)
    weekly_parser.add_argument(
        "--force", action="store_true", help="refetch offers even if this week's are loaded"
    )
    weekly_parser.add_argument(
        "--database-url", help="default: DATABASE_URL, else data/cheaprecipe.db"
    )

    recipes = subparsers.add_parser("recipes", help="retrieve recipes for the offers")
    recipes.add_argument(
        "--store",
        default="edeka",
        choices=vocabulary.STORES,
        help="whose classified offers to read; also names the output file",
    )
    recipes.add_argument(
        "--offers", type=Path, help="default: data/<store>_offers_classified.csv"
    )
    recipes.add_argument("--out", type=Path, help="default: data/<store>_recipes.json")
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
    setup_logging("DEBUG" if args.verbose else None)  # else LOG_LEVEL, default INFO

    try:
        if args.command == "offers":
            build_offers(
                out_dir=args.out_dir,
                store=args.store,
                store_id=args.store_id,
                skip_llm=args.skip_llm,
            )
        elif args.command == "weekly":
            weekly(store=args.store, force=args.force, database_url=args.database_url)
        elif args.command == "load":
            load(
                store=args.store,
                store_id=args.store_id,
                offers_path=args.offers,
                recipes_path=args.recipes,
                database_url=args.database_url,
            )
        else:
            build_recipes(
                offers_path=args.offers,
                out_path=args.out,
                store=args.store,
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
