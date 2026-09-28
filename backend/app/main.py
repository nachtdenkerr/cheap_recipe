"""FastAPI application entrypoint.

The adapter layer: it imports `cheaprecipe`, never the reverse.

Run from backend/: `uv run uvicorn app.main:app --reload`. The Vite dev server
proxies /api/* here with the prefix stripped, so routes carry no /api.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from cheaprecipe.db.session import init_db
from fastapi import FastAPI

from app.routers import auth, generate, nutrition, recipes, shopping


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(title="cheap_recipe", version="0.1.0", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(generate.router)
app.include_router(recipes.router)
app.include_router(shopping.router)
app.include_router(nutrition.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
