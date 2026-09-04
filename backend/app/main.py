"""FastAPI application entrypoint.

The adapter layer: it imports `cheaprecipe`, never the reverse.
"""

from fastapi import FastAPI

from app.routers import auth, generate, nutrition, recipes, shopping

app = FastAPI(title="cheap_recipe", version="0.1.0")

app.include_router(auth.router)
app.include_router(generate.router)
app.include_router(recipes.router)
app.include_router(shopping.router)
app.include_router(nutrition.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
