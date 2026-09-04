# cheap_recipe

Trying to save some pennies on groceries? `cheap_recipe` reads this week's
reduced-price items from your local supermarket and turns them into recipes you
can actually cook — so the discounts decide the menu, not the other way around.

Powered by AI (it's just an LLM tbh).

## How it works

The hard part isn't finding recipes; it's that supermarket offers don't look
like ingredients. `Hofglück zarte Schweinenackensteaks natur` is a brand, a
texture, a cut and a preparation note glued together — no recipe API has ever
heard of it. So the pipeline earns its keep in the middle:

```text
EDEKA offers          →  ingestion/      raw JSON from the store's offers endpoint
  ↓                                      189 offers this week
drop the non-food     →  normalization/  Drogerie, Tiernahrung, cookware, decor
  ↓                                      165 left
tidy + date the offer →  normalization/  "Ab Donnerstag erhältlich: Grana Padano"
  ↓                                      → title + validFrom = Thursday
German → ingredient   →  normalization/  LLM: → "grana padano cheese"
  ↓
classify each one     →  normalization/  can_cook? vegan/vegetarian/normal?
  ↓                                      for cooking / baking / drinks?
pick what fits you    →  selection/      41 vegan · 64 vegetarian · 100 normal
  ↓
find recipes          →  matching/       Spoonacular findByIngredients
  ↓
plan & check          →  agents/         planner proposes, critic pushes back
  ↓
cost it out           →  calculation/    price, nutrition, leftovers, allergens
  ↓
rank                  →  ranking/
```

Two rules shape the design:

- **The LLM normalizes and proposes; it never does arithmetic.** Cost, nutrition,
  waste and allergen filtering live in `calculation/` as deterministic code, so a
  hallucinated number can't reach a shopping list — or an allergy sufferer.
- **Model calls are batched over distinct values.** 165 offers collapse to far
  fewer unique titles, and each batch is one request. Naive per-row calls are
  the difference between a few seconds and a few minutes.

## Status

The ingestion → selection → recipe-retrieval path runs end to end. Everything
downstream of it is scaffolded but not yet written:

| Stage | State |
| --- | --- |
| `ingestion/` EDEKA fetch + parse | works |
| `normalization/` cleaning, translation, classification | works |
| `selection/` diet and use-case filtering | works |
| `matching/` Spoonacular retrieval | works |
| `agents/` planner, critic, loop | stub |
| `calculation/` nutrition, cost, waste, allergens | stub |
| `ranking/`, `db/`, `observability/`, `app/` API, `frontend/` | stub |

Known rough edges: the EDEKA endpoint is reached with a captured browser
session, so the cookies in `ingestion/edeka.py` go stale and need recapturing;
one market is hardcoded as the default; and the recipe API is queried with only
the ten cheapest ingredients.

## Getting started

Requires Python 3.9+ and [uv](https://docs.astral.sh/uv/).

```bash
cd backend
uv sync --extra dev
```

Put your keys in `keys.env` at the repo root (gitignored):

```text
OPENROUTER_API_KEY=...
SPOONACULAR_API_KEY=...
```

Then run the pipeline:

```bash
# fetch offers → clean → translate → classify, writing a CSV per stage to data/
uv run python scripts/fetch_edeka.py

# skip the LLM stages (no API spend, no network beyond EDEKA)
uv run python scripts/fetch_edeka.py --skip-llm

# retrieve recipes for the classified offers
uv run python scripts/load_recipes.py --diet vegetarian --use cooking
```

Every model call goes through `src/cheaprecipe/llm.py`, which points the OpenAI
SDK at OpenRouter. Changing model or vendor is one line there.

Tests:

```bash
uv run pytest
```

`tests/` is split deliberately: deterministic tests assert on `calculation/` and
`normalization/` and never touch the network, while LLM evals are their own
thing and are expected to be flaky.

## Structure

```text
cheap_recipe/
  backend/
    app/                  # FastAPI adapter — imports src, never the reverse
      routers/  (auth, generate, recipes, shopping, nutrition)
      schemas/  deps.py  main.py
    src/cheaprecipe/
      ingestion/          # EDEKA fetch/parse
      normalization/      # raw→canonical (+ cache table logic)
      selection/          # pick items per category by preference
      matching/           # recipe↔ingredient index, candidate retrieval
      agents/             # planner, critic, loop.py (orchestrator)
      calculation/        # nutrition, waste, cost, allergen filter (deterministic)
      ranking/            # phase-2 seam, trivial heuristic for now
      db/                 # models, repositories, migrations
      observability/      # Langfuse client + decorators
      config.py  llm.py   # keys.env loading, OpenRouter client
    tests/                # deterministic (assert on calculation) + LLM evals
    scripts/              # seed_db, load_recipes, fetch_edeka (thin, import src)
    data/                 # seed files + local dev SQLite (gitignored .db)
    pyproject.toml        # uv
  frontend/               # separate npm project
  workflow.ipynb          # the original prototype the pipeline came from
```

`app/` may import `src/cheaprecipe`; the reverse is never allowed. That keeps
the pipeline runnable from a script, a notebook or a test without dragging a web
framework along.
