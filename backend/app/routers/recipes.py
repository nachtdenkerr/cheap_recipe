"""Recipe endpoints: browse the latest suggestions, heart them, plan them."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import CurrentUser, SessionDep
from app.presenters import favourite_ids, latest_generation, recipe_out
from app.schemas.recipes import Recipe
from cheaprecipe.db.models import Generation, RecipeCache, User, UserPreference

router = APIRouter(prefix="/recipes", tags=["recipes"])


def _newest_generation_with(session, user: User, recipe_id: int) -> Generation | None:
    return session.scalars(
        select(Generation)
        .where(
            Generation.user_id == user.id,
            Generation.recipes.any(RecipeCache.id == recipe_id),
        )
        .order_by(Generation.created_at.desc(), Generation.id.desc())
        .limit(1)
    ).first()


def _visible(session, user: User, recipe_id: int) -> tuple[RecipeCache, Generation]:
    """A recipe the user has been suggested, with the newest plan that has it."""
    generation = _newest_generation_with(session, user, recipe_id)
    recipe = session.get(RecipeCache, recipe_id) if generation else None
    if recipe is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recipe not found")
    return recipe, generation


def _in_latest(session, user: User, recipe_id: int) -> tuple[RecipeCache, Generation]:
    """A recipe from the current suggestions — the only ones that can be planned."""
    generation = latest_generation(session, user)
    recipe = next(
        (r for r in (generation.recipes if generation else []) if r.id == recipe_id), None
    )
    if recipe is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Recipe is not among this week's suggestions"
        )
    return recipe, generation


@router.get("")
def list_recipes(user: CurrentUser, session: SessionDep) -> list[Recipe]:
    """The recipes of the user's most recent plan; empty before the first one."""
    generation = latest_generation(session, user)
    if generation is None:
        return []
    favourites = favourite_ids(user)
    return [recipe_out(recipe, generation, favourites) for recipe in generation.recipes]


@router.get("/{recipe_id}")
def get_recipe(recipe_id: int, user: CurrentUser, session: SessionDep) -> Recipe:
    """One recipe, costed against the newest of the user's plans that has it."""
    recipe, generation = _visible(session, user, recipe_id)
    return recipe_out(recipe, generation, favourite_ids(user))


@router.post("/{recipe_id}/favourite")
def add_favourite(recipe_id: int, user: CurrentUser, session: SessionDep) -> Recipe:
    """Heart a recipe. Idempotent."""
    recipe, generation = _visible(session, user, recipe_id)
    pref = user.preference or UserPreference(user=user)
    if recipe not in pref.favourite_recipes:
        pref.favourite_recipes.append(recipe)
    session.add(pref)
    session.commit()
    return recipe_out(recipe, generation, favourite_ids(user))


@router.delete("/{recipe_id}/favourite")
def remove_favourite(recipe_id: int, user: CurrentUser, session: SessionDep) -> Recipe:
    recipe, generation = _visible(session, user, recipe_id)
    if user.preference is not None and recipe in user.preference.favourite_recipes:
        user.preference.favourite_recipes.remove(recipe)
        session.commit()
    return recipe_out(recipe, generation, favourite_ids(user))


@router.post("/{recipe_id}/meal-plan")
def add_to_meal_plan(recipe_id: int, user: CurrentUser, session: SessionDep) -> Recipe:
    """Plan a recipe this week; its offers join the shopping list. Idempotent."""
    recipe, generation = _in_latest(session, user, recipe_id)
    if recipe not in generation.planned_recipes:
        generation.planned_recipes.append(recipe)
        session.commit()
    return recipe_out(recipe, generation, favourite_ids(user))


@router.delete("/{recipe_id}/meal-plan")
def remove_from_meal_plan(recipe_id: int, user: CurrentUser, session: SessionDep) -> Recipe:
    recipe, generation = _in_latest(session, user, recipe_id)
    if recipe in generation.planned_recipes:
        generation.planned_recipes.remove(recipe)
        session.commit()
    return recipe_out(recipe, generation, favourite_ids(user))
