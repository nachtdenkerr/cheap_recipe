"""FastAPI application entrypoint.

The adapter layer: it imports `cheaprecipe`, never the reverse.

Run from backend/: `uv run uvicorn app.main:app --reload`. The Vite dev server
proxies /api/* here with the prefix stripped, so routes carry no /api.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from app import scheduler
from app.routers import auth, generate, markets, mealplan, nutrition, recipes, shopping
from cheaprecipe.db.session import SessionLocal, database_url, init_db
from cheaprecipe.logging_setup import setup_logging
from cheaprecipe.observability.tracing import setup_tracing

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # The same logging as the pipeline CLI: terminal plus logs/cheaprecipe.log,
    # so the planner's and the critic's steps are visible and kept.
    path = setup_logging()
    # Agent traces to Phoenix, when PHOENIX_COLLECTOR_ENDPOINT is set.
    tracing = setup_tracing()
    init_db()
    log.info(
        "API ready — database %s, log file %s, tracing %s, weekly refresh %s",
        database_url(), path or "off", "on" if tracing else "off",
        "on" if scheduler.enabled() else "off",
    )

    # This week's offers and recipe pool, kept current without a cron job.
    stop = asyncio.Event()
    task = asyncio.create_task(scheduler.refresh_loop(SessionLocal, stop)) if scheduler.enabled() else None
    yield
    stop.set()
    if task is not None:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="cheap_recipe", version="0.1.0", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(generate.router)
app.include_router(recipes.router)
app.include_router(shopping.router)
app.include_router(nutrition.router)
app.include_router(markets.router)
app.include_router(mealplan.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
