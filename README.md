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
store offers          →  ingestion/      EDEKA's offers endpoint, or ALDI's page
  ↓                                      189 offers this week
drop the non-food     →  normalization/  each chain's own departments, per
  ↓                                      excluded_categories.yml — 165 left
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

## How a week is planned

Every plan — the weekly one and each follow-up request — is made by the
planner agent and reviewed by the critic agent, in a loop
(`agents/loop.py`):

1. **Code narrows the pool.** Recipes that break the user's diet, contain an
   allergen or a disliked ingredient, take longer than their freest day, or
   use fewer than 3 of this week's offers never reach a model.
2. **The labeller says what each dish is** — its kind (pasta, rice, curry…)
   and main ingredient — once per recipe, stored on it (`agents/labels.py`).
3. **The planner agent chooses the week**, with deterministic tools:
   `build_greedy_plan` (the cheapest, least wasteful week that keeps to the
   variety rules), `estimate_leftovers`, `price_recipe`. It answers with
   recipe names; the priced plan is built from them in code, and an answer
   that breaks the rules is sent back to it before it counts.
4. **The critic agent reviews the week**: it labels the dishes and judges
   what needs taste — a sensible week, the user's notes. The variety rules
   (one dish per kind, a main ingredient at most twice) are counted from the
   labels in code, and cooking time against the user's week is computed.
5. **A rejected week goes back to the planner** with every issue raised so
   far, and it may not bring back a recipe already rejected. Up to 3 rounds;
   the last plan is kept with the critic's open issues if none passes.

### Watching it plan

Planning takes a minute or more, so the page starts it as a job
(`POST /generate/jobs/weekly` or `/refine`, then `GET /generate/jobs/{id}`)
and shows each step as the planning reports it — checking the offers,
getting to know new dishes, each planner and critic round — while
ingredients drop into a bowl. When the week is ready a dish rises out of
it, and the recipes appear with the critic's assessment under "Why this
week". `POST /generate` and `/generate/refine` still answer in one request.

### Evaluating the planner

`backend/evals` replays frozen weeks through the real planner and critic for
a set of typical users (`evals/profiles.py`), and measures each week: did the
critic pass it, rounds, tokens, cost against the greedy week, variety
repeats, unsafe recipes (diet, allergen, dislike — must be 0), and empty
meals in the grid.

```bash
cd backend
uv run python -m evals.freeze --branch 10001604 --name edeka-frank   # this week, from the database
uv run python -m evals.run                                         # every fixture × profile
uv run python -m evals.run --profile no-pork --fixture edeka-frank
```

Each run writes `evals/results/<time>.json` and prints the change against
the previous report. It uses real model calls (tokens) but never
Spoonacular. Fixtures and reports hold store and Spoonacular data, so they
stay local.

## Status

The ingestion → selection → recipe-retrieval path runs end to end. Everything
downstream of it is scaffolded but not yet written:

| Stage | State |
| --- | --- |
| `ingestion/` EDEKA + ALDI SÜD fetch/parse | works |
| `normalization/` cleaning, translation, classification | works |
| `selection/` diet and use-case filtering | works |
| `matching/` Spoonacular retrieval | works |
| `agents/` planner, critic, labeller, loop | works |
| `calculation/` cost, waste, allergens, diet, pantry | works |
| `db/`, `observability/`, `app/` API, `frontend/` | works |
| `ranking/`, nutrition | stub |

Known rough edges: neither source is a documented API, so both can change shape
without notice; one market and one ALDI category are hardcoded as the defaults;
ALDI publishes no offer end date, so its rows carry no `validTill`; and the
recipe API is queried with only the ten cheapest ingredients.

## Getting started

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
cd backend
uv sync --extra dev
```

Put your keys in `.env` at the repo root (gitignored):

```text
OPENROUTER_API_KEY=...
SPOONACULAR_API_KEY=...
```

Neither store needs credentials — no cookie, no key. One caveat for EDEKA: do
not give it a spoofed browser user-agent. The edge rejects a request claiming to
be Chrome or Firefox without a matching TLS fingerprint, so adding a browser UA
causes the 403 it looks like it should prevent.

ALDI SÜD has no offers endpoint at all: its commerce API is not reachable
without the front end's own credentials, so `ingestion/aldi.py` reads the
offers out of the `__NUXT_DATA__` payload the category page server-renders.

Then run the pipeline:

```bash
# fetch offers → clean → translate → classify, writing a CSV per stage to data/
uv run cheaprecipe offers

# the same, from ALDI SÜD's weekly offers
uv run cheaprecipe offers --store aldi

# skip the LLM stages (no API spend, no network beyond the store)
uv run cheaprecipe offers --skip-llm

# retrieve recipes for the classified offers
uv run cheaprecipe recipes --diet vegetarian --use cooking

# load both into the API's database (data/cheaprecipe.db); safe to re-run
uv run cheaprecipe load
```

The commands run through `src/cheaprecipe/pipeline.py`, the one orchestration
layer; `scripts/dry_run_plan.py` plans from the saved files without a database
(`--llm` adds the planner/critic loop). Every stage logs what it
started, what it produced, and how many records it dropped on the way; add `-v`
for per-batch LLM calls, token counts and HTTP detail. A failure logs the
traceback against the stage that raised it and exits non-zero.

Every model call goes through `src/cheaprecipe/llm.py`, which points the OpenAI
SDK at OpenRouter. Changing model or vendor is one line there.

Run the app — the API, then the frontend (http://localhost:5173, which proxies
`/api` to the API):

```bash
cd backend && uv run uvicorn app.main:app --reload
cd frontend && npm install && npm run dev      # VITE_USE_MOCK=true for mock data
```

### The database schema

The schema is versioned with Alembic (`backend/src/cheaprecipe/db/migrations`).
The API and the CLI bring the database up to date when they start; a
database made before migrations existed is stamped as the baseline and keeps
its data. After changing a model:

```bash
cd backend
uv run alembic revision --autogenerate -m "what changed"   # review the file it writes
uv run alembic upgrade head                                # or just restart the API
```

`tests/test_migrations.py` fails when a model changes without a migration.

### Home supermarkets

Offers are per branch, so every user picks up to 3 home supermarkets in their
profile, and their plans use those branches' offers only. Without one,
planning answers "set your home supermarket first". The profile's search
(`GET /markets?q=`) asks EDEKA's own market finder by name, street, town or
postcode, and falls back to the branches already known when it is
unreachable; ALDI SÜD is one entry, as its offers are the same nationwide. A
newly chosen branch has its offers loaded in the background right away.

### The weekly refresh

Offers change every Monday, so the API keeps itself current: a background
task (`app/scheduler.py`) runs `cheaprecipe/refresh.py` once a week for every
branch some user has as a home supermarket, from Monday 05:00 German time — or
as soon as the API starts, if it was off.

1. this week's offers are fetched, classified and loaded (skipped if already
   loaded — this step calls the LLM);
2. for every diet any user has, plus no restriction, the recipe pool is checked:
   fewer than 8 recipes that fit the diet and use 3+ of this week's offers, and
   Spoonacular is searched for more.

When one user's own filters (allergens, ingredients they don't eat, recipes
already suggested) leave too few, the request tops the pool up for them, with
those filters passed to Spoonacular. Searches are recorded (`recipe_fetch`) and
capped per week to protect the quota; `weekly_refresh` records each run.

```text
WEEKLY_REFRESH=off          # don't run it (e.g. a cron runs `cheaprecipe weekly`)
REFRESH_HOUR=5              # from when on Monday
RECIPE_TOPUP=off            # no fetching during requests
```

`uv run cheaprecipe weekly` runs the same refresh by hand, for the same
branches (EDEKA's default branch while no one has chosen one; `--force`
refetches the offers).

### Logs and traces

Everything the pipeline and the API do is logged to the terminal and to
`backend/logs/cheaprecipe.log` (rotating, gitignored): each plan, the
planner's picks, each critic round with its issues. `LOG_LEVEL=DEBUG` for more;
`LOG_FILE=` (empty) to turn the file off.

For the agents' full traces — prompts, tool calls with arguments and results,
answers, retries, tokens — run [Arize Phoenix](https://phoenix.arize.com)
locally; nothing leaves your machine:

```bash
uvx arize-phoenix serve                     # UI on http://localhost:6006
# in .env:  PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006
cd backend && uv run --extra tracing uvicorn app.main:app --reload
```

Every plan is one trace (the planner/critic loop), tagged with the user and
the request: `metadata.request` is `weekly` or `refine`, and a refine also
carries `metadata.mode` and `metadata.note`.

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
      ingestion/          # EDEKA + ALDI SÜD fetch/parse
      normalization/      # raw→canonical (+ cache table logic)
      selection/          # pick items per category by preference
      matching/           # recipe↔ingredient index, candidate retrieval
      agents/             # planner, critic, loop.py (orchestrator)
      calculation/        # nutrition, waste, cost, allergen filter (deterministic)
      ranking/            # phase-2 seam, trivial heuristic for now
      db/                 # models, repositories, migrations
      observability/      # Langfuse client + decorators
      config.py  llm.py   # .env loading, OpenRouter client
      vocabulary.py       # the closed vocabularies + store config loader
      excluded_categories.yml  # per-chain non-food departments, editable
      pipeline.py         # stage orchestration + `cheaprecipe` CLI
      logging_setup.py    # rich console logging, stage() timer
    tests/                # deterministic (assert on calculation) + LLM evals
    data/                 # seed files + local dev SQLite (gitignored .db)
    pyproject.toml        # uv
  frontend/               # separate npm project
```

`app/` may import `src/cheaprecipe`; the reverse is never allowed. That keeps
the pipeline runnable from a script, a notebook or a test without dragging a web
framework along.
