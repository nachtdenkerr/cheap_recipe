# cheap_recipe

Trying to save some pennies from groceries shopping? Now you can easily access world-class recipes curated from those reduced-price items, powered by AI (it's just LLM thb)

## structure

´´´plain text
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
    tests/                # deterministic (assert on calculation) + LLM evals
    scripts/              # seed_db, load_recipes, fetch_edeka (thin, import src)
    data/                 # seed files + local dev SQLite (gitignored .db)
    pyproject.toml        # uv
  frontend/               # separate npm project´´´
  