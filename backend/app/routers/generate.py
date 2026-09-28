"""Recipe generation: plan a week from the current offers and store the result.

Reads the user's preferences, turns the database rows into the agent layer's
contracts, hands them to the planner and persists the `Plan` it returns as a
`Generation` — which is what /recipes and /shopping then read.

Two kinds of run:

- the weekly plan (`POST /generate`), once per week and free: the greedy
  planner, with recipes too long for any day filtered out in code;
- a refine (`POST /generate/refine`): keeps the recipes the user planned and
  swaps the rest, optionally favouring what is already in their fridge. The
  planner agent and the critic run in a loop (agents/loop.py), and the
  critic's verdict is stored on the Generation. Limited per week
  (app/quota.py) because it spends LLM tokens.
"""

import logging
from collections.abc import Iterable
from datetime import datetime

from cheaprecipe.agents import critic, loop, planner
from cheaprecipe.agents.contracts import (
    Critique,
    Ingredient,
    Item,
    Plan,
    Quantity,
    Recipe,
    UserPreference,
)
from cheaprecipe.db.models import (
    Address,
    Generation,
    GenerationItem,
    Offer,
    RecipeCache,
    User,
)
from cheaprecipe.vocabulary import CUISINES
from fastapi import APIRouter, HTTPException, status
from pydantic_ai.exceptions import AgentRunError
from sqlalchemy import or_, select

from app.deps import CurrentUser, SessionDep
from app.presenters import favourite_ids, latest_generation, recipe_out
from app.quota import STORE_TZ, generations_this_week, refine_quota, week_bounds
from app.schemas.generate import (
    GenerateRequest,
    RefineQuota,
    RefineRequest,
    RefineResponse,
)
from app.schemas.recipes import Recipe as RecipeOut

log = logging.getLogger(__name__)

router = APIRouter(prefix="/generate", tags=["generate"])

# Database unit -> (contracts.Unit, factor).
_UNITS = {
    "g": ("g", 1.0),
    "kg": ("kg", 1.0),
    "l": ("l", 1.0),
    "ml": ("l", 0.001),
    "stück": ("Stück", 1.0),
    "stk": ("Stück", 1.0),
    "piece": ("Stück", 1.0),
    "pieces": ("Stück", 1.0),
}


def _quantity(amount: float | None, unit: str | None) -> Quantity | None:
    known = _UNITS.get((unit or "").strip().lower())
    if amount is None or known is None:
        return None
    return Quantity(amount=amount * known[1], unit=known[0])


def _current_offers(session, user: User) -> list[Offer]:
    """Offers still valid today, from the user's supermarket when they chose one."""
    today = datetime.now(STORE_TZ).date()
    query = select(Offer).where(or_(Offer.valid_till.is_(None), Offer.valid_till >= today))
    pref = user.preference
    if pref is not None and pref.fav_supermarket_id is not None:
        query = query.join(Address).where(Address.supermarket_id == pref.fav_supermarket_id)
    return list(session.scalars(query))


def _items(offers: list[Offer]) -> list[Item]:
    items = []
    for offer in offers:
        quantity = _quantity(offer.quantity_amount, offer.quantity_unit)
        ppu_unit = _UNITS.get((offer.price_per_unit_unit or "").lower())
        if quantity is None or offer.price_per_unit is None or ppu_unit is None:
            continue  # the planner cannot price what it cannot measure
        items.append(
            Item(
                name=offer.ingredient_en or offer.title,
                quantity=quantity,
                price=offer.price,
                price_per_unit=offer.price_per_unit,
                price_per_unit_unit=ppu_unit[0],
                sale_start_date=offer.valid_from,
                offer_id=offer.id,
            )
        )
    return items


def _candidate(row: RecipeCache, offered: set[int]) -> Recipe:
    ingredients = []
    for line in row.ingredients:
        quantity = _quantity(line.amount, line.unit)
        if quantity is None:
            log.debug("recipe %s: skipping %r, unit %r", row.id, line.name, line.unit)
            continue
        ingredients.append(
            Ingredient(
                name=line.name,
                quantity=quantity,
                from_offer=line.canonical_ingredient_id in offered,
            )
        )
    return Recipe(
        name=row.name,
        ingredients=ingredients,
        cooking_instructions=row.instructions,
        servings=row.servings or 1,
        cooking_time=row.cooking_time or row.total_time or 0,
        cuisine=[row.cuisine.name] if row.cuisine and row.cuisine.name in CUISINES else [],
        total_kcal=row.total_kcal,
        source=row.source,
        external_id=str(row.id),
    )


def _allergen_free(row: RecipeCache, excluded: set[str]) -> bool:
    """Deterministic allergen filter over the canonical ingredients — never the LLM."""
    return not any(
        excluded.intersection(line.canonical_ingredient.allergens or [])
        for line in row.ingredients
        if line.canonical_ingredient is not None
    )


def _pantry_items(names: Iterable[str]) -> list[Item]:
    """Fridge items as free offers, so the basket counts them as already bought.

    The amount is unknown, so each is a nominal 1 kg: enough that any recipe
    using it pays nothing for it, which is what steers the greedy planner
    towards those recipes.
    """
    return [
        Item(
            name=name,
            quantity=Quantity(amount=1, unit="kg"),
            price=0.0,
            price_per_unit=0.0,
            price_per_unit_unit="kg",
        )
        for name in names
    ]


def _max_day_minutes(user: User) -> int | None:
    """The freest day's cooking time, or None when the user has not said."""
    pref = user.preference
    week = pref.week_time_availability if pref else None
    return max(week) if week else None


def _user_pref(user: User, note: str | None) -> UserPreference:
    pref = user.preference
    return UserPreference(
        week_time_availability=pref.week_time_availability if pref else None,
        notes=note,
    )


def _run_planner(
    session,
    user: User,
    number_of_meals: int,
    exclude_ids: set[int] = frozenset(),
    pantry_items: Iterable[str] = (),
    note: str | None = None,
    fixed: list[RecipeCache] | None = None,
) -> tuple[Plan, dict[str, RecipeCache], Critique | None]:
    """Plan from the current offers.

    Returns the plan, its candidate rows by id, and the critic's verdict.

    Without `fixed` this is the free, deterministic greedy plan (no verdict).
    With it — a refine topping up the recipes the user already chose — the
    planner agent and the critic run in a loop (agents/loop.py), judging the
    new recipes together with the chosen ones. That is the LLM path, and why
    refines are rate-limited.
    """
    pref = user.preference
    excluded = {a.lower() for a in (pref.allergens if pref else None) or []}
    longest_day = _max_day_minutes(user)

    offers = _current_offers(session, user)
    offered = {o.canonical_ingredient_id for o in offers if o.canonical_ingredient_id}
    rows = {
        str(row.id): row
        for row in session.scalars(select(RecipeCache))
        if row.id not in exclude_ids and _allergen_free(row, excluded)
    }
    if not offers or not rows:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No current offers or candidate recipes to plan from; run ingestion first",
        )

    candidates = [_candidate(row, offered) for row in rows.values()]
    if longest_day is not None:
        # A recipe longer than the freest day fits no day. Deterministic, so the
        # free weekly plan respects cooking time without the critic.
        candidates = [c for c in candidates if critic.total_minutes(c) <= longest_day]
        if not candidates:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "No recipes fit your cooking time this week"
            )

    items = _items(offers) + _pantry_items(pantry_items)
    verdict = None
    try:
        if fixed is None:
            plan = planner.plan(candidates, items, number_of_meals)
        else:
            result = loop.run(
                candidates,
                items,
                number_of_meals,
                user_pref=_user_pref(user, note),
                fixed=[_candidate(row, offered) for row in fixed],
            )
            plan, verdict = result.plan, result.critique
    except NotImplementedError as exc:
        # A planning step that is still a stub.
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, "Meal planning is not implemented yet"
        ) from exc
    except (RuntimeError, AgentRunError) as exc:
        # No OPENROUTER_API_KEY, the provider failing, or a model that never
        # produced a valid answer within its request limit.
        log.error("planner unavailable: %s", exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The planner is unavailable right now"
        ) from exc
    return plan, rows, verdict


def _grocery_items(plan: Plan, skip_offer_ids: set[int] = frozenset()) -> list[GenerationItem]:
    return [
        GenerationItem(
            offer_id=item.offer_id,
            name=None if item.offer_id else item.name,
            amount=item.quantity.amount,
            unit=item.quantity.unit,
        )
        for item in plan.grocery_list
        # Fridge items (price 0, no offer) are not shopping.
        if item.offer_id is not None or item.price > 0
        if item.offer_id not in skip_offer_ids
    ]


def _recipes_out(generation: Generation, user: User) -> list[RecipeOut]:
    favourites = favourite_ids(user)
    return [recipe_out(recipe, generation, favourites) for recipe in generation.recipes]


@router.post("")
def generate(
    user: CurrentUser, session: SessionDep, body: GenerateRequest | None = None
) -> list[RecipeOut]:
    """The week's first plan. Free, and once per week — later changes are refines."""
    if generations_this_week(session, user, "weekly") > 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This week is already planned; ask for new recipes instead",
        )
    body = body or GenerateRequest()
    plan, rows, _ = _run_planner(session, user, body.number_of_meals)

    pref = user.preference
    generation = Generation(
        user=user,
        kind="weekly",
        diet_type=pref.diet_type if pref else None,
        model="greedy",
        total_cost=plan.total_cost,
        recipes=[rows[r.external_id] for r in plan.recipes if r.external_id in rows],
        items=_grocery_items(plan),
    )
    session.add(generation)
    session.commit()
    return _recipes_out(generation, user)


@router.get("/quota")
def quota(user: CurrentUser, session: SessionDep) -> RefineQuota:
    return refine_quota(session, user)


@router.post("/refine")
def refine(body: RefineRequest, user: CurrentUser, session: SessionDep) -> RefineResponse:
    """Keep the planned recipes, replace the rest with ones not seen this week."""
    if refine_quota(session, user).remaining == 0:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "No recipe requests left this week"
        )

    week_start, _ = week_bounds()
    current = latest_generation(session, user)
    if current is None or current.created_at < week_start:
        raise HTTPException(status.HTTP_409_CONFLICT, "Plan your week first")

    planned = list(current.planned_recipes)
    count = body.count or max(len(current.recipes) - len(planned), 1)

    # Everything suggested this week, planned or not, so replacements are new.
    seen = {
        recipe.id
        for generation in session.scalars(
            select(Generation).where(
                Generation.user_id == user.id, Generation.created_at >= week_start
            )
        )
        for recipe in generation.recipes
    }
    plan, rows, verdict = _run_planner(
        session, user, count, exclude_ids=seen,
        pantry_items=body.pantry_items or (), note=body.note, fixed=planned,
    )
    new = [rows[r.external_id] for r in plan.recipes if r.external_id in rows]
    if not new:
        # Nothing written, so the request does not use up the quota.
        raise HTTPException(
            status.HTTP_409_CONFLICT, "No new recipes fit this week's offers"
        )

    # Carry the planned recipes' shopping lines over, ticks included.
    planned_ingredients = {
        line.canonical_ingredient_id
        for recipe in planned
        for line in recipe.ingredients
        if line.canonical_ingredient_id is not None
    }
    carried = [
        GenerationItem(
            offer_id=item.offer_id, name=item.name, amount=item.amount,
            unit=item.unit, checked=item.checked,
        )
        for item in current.items
        if item.offer is not None
        and item.offer.canonical_ingredient_id in planned_ingredients
    ]

    pref = user.preference
    generation = Generation(
        user=user,
        kind="refine",
        diet_type=pref.diet_type if pref else None,
        model="agent+critic",
        total_cost=plan.total_cost,
        pantry_items=body.pantry_items or None,
        note=body.note,
        # The critic's verdict on the whole week, kept even when the rounds ran
        # out without a pass — it says what is still wrong.
        passed=verdict.passed if verdict else None,
        issues=verdict.issues if verdict else None,
        suggestions=verdict.suggestions if verdict else None,
        recipes=planned + new,
        planned_recipes=planned,
        items=carried + _grocery_items(plan, {i.offer_id for i in carried}),
    )
    session.add(generation)
    session.commit()
    return RefineResponse(
        recipes=_recipes_out(generation, user), quota=refine_quota(session, user)
    )
