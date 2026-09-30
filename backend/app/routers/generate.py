"""Recipe generation: plan a week from the current offers and store the result.

Reads the user's preferences, turns the database rows into the agent layer's
contracts, hands them to the planner and persists the `Plan` it returns as a
`Generation` — which is what /recipes and /shopping then read.

Every plan is made by the planner agent and reviewed by the critic, in a
loop (agents/loop.py): the agent plans with the deterministic tools (cost,
leftovers, a greedy baseline), the critic judges the week, and a rejected
plan goes back to the agent with the critic's issues until it passes or the
rounds run out. The critic's verdict is stored on the Generation.

Code does what code can do first: the candidate pool is filtered for diet,
allergens, dislikes, time and offer use before the agent sees it.

Two kinds of run:

- the weekly plan (`POST /generate`), once per week;
- a refine (`POST /generate/refine`): keeps the recipes the user planned and
  swaps the rest, optionally favouring what is already in their fridge; the
  critic judges the new recipes together with the kept ones. Limited per
  week (app/quota.py).
"""

import logging
import os
from collections.abc import Iterable

from fastapi import APIRouter, HTTPException, status
from pydantic_ai.exceptions import AgentRunError
from sqlalchemy import select

from app.deps import CurrentUser, SessionDep
from app.methods import prepare_methods
from app.presenters import favourite_ids, latest_generation, recipe_out, shopping_name
from app.quota import generations_this_week, refine_quota, week_bounds
from app.schemas.generate import (
    GenerateRequest,
    RefineQuota,
    RefineRequest,
    RefineResponse,
)
from app.schemas.recipes import Recipe as RecipeOut
from cheaprecipe import refresh
from cheaprecipe.agents import critic, labels, loop, planner
from cheaprecipe.agents.contracts import (
    Critique,
    Item,
    Plan,
    Quantity,
    Recipe,
    UserPreference,
)
from cheaprecipe.calculation.diet import fits
from cheaprecipe.calculation.pantry import is_pantry
from cheaprecipe.config import load_keys
from cheaprecipe.db.adapters import allergen_free as _allergen_free
from cheaprecipe.db.adapters import avoids as _avoids
from cheaprecipe.db.adapters import current_offers
from cheaprecipe.db.adapters import offer_items as _items
from cheaprecipe.db.adapters import recipe_candidate as _candidate
from cheaprecipe.db.load import chain_of
from cheaprecipe.db.models import (
    Address,
    Generation,
    GenerationItem,
    Offer,
    RecipeCache,
    User,
)
from cheaprecipe.observability.tracing import trace_context
from cheaprecipe.vocabulary import DEFAULT_MEAL_TYPES

log = logging.getLogger(__name__)

router = APIRouter(prefix="/generate", tags=["generate"])

NO_HOME_MARKET = "Set your home supermarket in your profile first, so we know whose offers to plan with."
OFFERS_LOADING = "This week's offers for your supermarket are still being loaded; try again in a few minutes."


def _home_markets(user: User) -> list[Address]:
    pref = user.preference
    return list(pref.home_markets) if pref else []


def _current_offers(session, user: User) -> list[Offer]:
    """Offers still valid today at the user's home markets — 409 without any."""
    markets = _home_markets(user)
    if not markets:
        raise HTTPException(status.HTTP_409_CONFLICT, NO_HOME_MARKET)
    offers = current_offers(session, [m.id for m in markets])
    if not offers:
        raise HTTPException(status.HTTP_409_CONFLICT, OFFERS_LOADING)
    return offers


def _topup_enabled() -> bool:
    """RECIPE_TOPUP=off stops requests from fetching recipes (the weekly refresh still does)."""
    load_keys()
    return os.environ.get("RECIPE_TOPUP", "on").strip().lower() not in {"off", "false", "0", "no"}


def _store_of(user: User) -> str:
    """The chain of the user's first home market (for refresh.py's fetch caps)."""
    markets = _home_markets(user)
    return chain_of(markets[0]) if markets else "edeka"


def _filter_pool(session, offered, items, exclude_ids, diet, excluded, dislikes, longest_day):
    """The recipe pool through each filter in turn.

    Returns the rows left (by id), the planner candidates among them that use
    enough offers, and the funnel: (label, how many were left, what to tell
    the user if that step left none).
    """
    rows = list(session.scalars(select(RecipeCache)))
    funnel = [("in the pool", len(rows), "No recipes are loaded yet; run ingestion first")]

    def keep(label: str, message: str, test) -> None:
        nonlocal rows
        rows = [row for row in rows if test(row)]
        funnel.append((label, len(rows), message))

    if exclude_ids:
        keep("not suggested this week", "Every recipe has been suggested this week",
             lambda row: row.id not in exclude_ids)
    if diet and diet != "normal":
        # A vegetarian gets vegetarian or vegan recipes only (calculation/diet.py);
        # a recipe loaded without a diet counts as "normal".
        keep(f"fit a {diet} diet", "No recipes this week fit your diet",
             lambda row: fits(row.diet_type, diet))
    if excluded:
        keep("free of your allergens", "No recipes this week avoid your allergens",
             lambda row: _allergen_free(row, excluded))
    if dislikes:
        keep("without what you don't eat",
             "No recipes this week avoid the ingredients you don't eat",
             lambda row: _avoids(row, dislikes))
    if longest_day is not None:
        # A recipe longer than the freest day fits no day.
        keep(f"fit a {longest_day}-minute day", "No recipes fit your cooking time this week",
             lambda row: critic.total_minutes(_candidate(row, offered)) <= longest_day)

    candidates = {str(row.id): _candidate(row, offered) for row in rows}
    usable = planner.using_offers(list(candidates.values()), items)
    funnel.append(
        (f"use {planner.DEFAULT_MIN_OFFERS}+ offers", len(usable), "No recipes use this week's offers")
    )
    return {str(row.id): row for row in rows}, usable, funnel


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


def _meal_types(user: User) -> list[str]:
    pref = user.preference
    return list((pref.meal_types if pref else None) or DEFAULT_MEAL_TYPES)


def _user_pref(user: User, note: str | None) -> UserPreference:
    pref = user.preference
    return UserPreference(
        week_time_availability=pref.week_time_availability if pref else None,
        notes=note,
        household_size=(pref.household_size if pref else None) or 1,
        meal_types=_meal_types(user),
    )


# The pool a plan chooses from: this many candidates per recipe to plan, per
# course, or the planner agent has no real choice to make.
CHOICE = 2


def _courses(user: User, number_of_meals: int, fixed: list[RecipeCache] = ()) -> dict[str, int]:
    """How many breakfast and main recipes to plan (planner.course_quotas).

    For a refine, the kept recipes count towards the week: a kept breakfast
    means the new recipes are mains.
    """
    week = planner.course_quotas(number_of_meals + len(fixed), _meal_types(user))
    for row in fixed:
        course = "breakfast" if row.course == "breakfast" else "main"
        if week.get(course):
            week[course] -= 1
    short = number_of_meals - sum(week.values())
    if short > 0:  # the kept recipes were not what the quotas expected
        week["main"] = week.get("main", 0) + short
    return {course: n for course, n in week.items() if n > 0}


def _run_planner(
    session,
    user: User,
    number_of_meals: int,
    exclude_ids: set[int] = frozenset(),
    pantry_items: Iterable[str] = (),
    note: str | None = None,
    fixed: list[RecipeCache] = (),
) -> tuple[Plan, dict[str, RecipeCache], Critique]:
    """Plan from the current offers: the planner agent and the critic, in a loop.

    Returns the plan, its candidate rows by id, and the critic's verdict.
    `fixed` are recipes the user already chose (a refine): not candidates, but
    judged together with the new ones, as variety and time are the week's.
    """
    pref = user.preference
    excluded = {a.lower() for a in (pref.allergens if pref else None) or []}
    diet = pref.diet_type if pref else None
    dislikes = list((pref.black_list if pref else None) or [])
    longest_day = _max_day_minutes(user)

    offers = _current_offers(session, user)
    offered = {o.canonical_ingredient_id for o in offers if o.canonical_ingredient_id}
    items = _items(offers) + _pantry_items(pantry_items)

    # Each filter in turn, deterministic — the LLM only ever sees what is left.
    def run_filters():
        return _filter_pool(
            session, offered, items, exclude_ids, diet, excluded, dislikes, longest_day
        )

    courses = _courses(user, number_of_meals, list(fixed))
    rows, usable, funnel = run_filters()
    candidates = _labelled(session, rows, usable) if usable else []

    def per_course(recipes: list[Recipe]) -> dict[str, int]:
        return {c: sum(1 for r in recipes if planner.course_of(r) == c) for c in courses}

    if _topup_enabled():
        # A pool with too little choice for this user, per course: ask
        # Spoonacular for recipes that fit them (capped per week —
        # refresh.py), then filter again.
        added = 0
        for course, have in per_course(candidates).items():
            want = CHOICE * courses[course]
            if have >= want:
                continue
            wanted = refresh.PoolFilter(
                diet=diet or "normal",
                allergens=frozenset(excluded),
                dislikes=tuple(dislikes),
                exclude_ids=frozenset(exclude_ids),
                course=course,
            )
            fetched = refresh.ensure_pool(
                session, _store_of(user), wanted, reason="top-up", minimum=want, offers=offers,
            )
            added += fetched.added
        if added:
            rows, usable, funnel = run_filters()
            candidates = _labelled(session, rows, usable) if usable else []
    log.info(
        "candidates: %s; by course %s for %s",
        " → ".join(f"{n} {label}" for label, n, _ in funnel), per_course(candidates), courses,
    )
    if not candidates:
        # Checked here, before any planning: an LLM run over no candidates
        # spends tokens to return nothing. The message names the step that
        # emptied the pool.
        emptied = next((message for _, n, message in funnel if n == 0), funnel[-1][2])
        raise HTTPException(status.HTTP_409_CONFLICT, emptied)

    try:
        result = loop.run(
            candidates,
            items,
            number_of_meals,
            user_pref=_user_pref(user, note),
            fixed=[_candidate(row, offered) for row in fixed],
            courses=courses,
        )
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
    log.info(
        "loop: %d round(s), critic %s",
        result.rounds, "passed" if result.critique.passed else f"still rejects: {result.critique.issues}",
    )
    return result.plan, rows, result.critique


def _labelled(session, rows: dict[str, RecipeCache], candidates: list[Recipe]) -> list[Recipe]:
    """The candidates with what kind of dish each is (agents/labels.py).

    Labelled once per recipe, in one model call for all the new ones, and
    stored — so the planner can plan a varied week from the start and the
    critic judges with the same labels. Without them (the model down) the
    loop still runs: the critic labels the plan itself.
    """
    missing = [c for c in candidates if c.kind is None or c.course is None]
    if missing:
        try:
            found = labels.label_dishes(missing)
        except (RuntimeError, AgentRunError) as exc:
            log.warning("could not label %d candidates: %s", len(missing), exc)
            return candidates
        for candidate in missing:
            label = found.get(candidate.name)
            row = rows.get(candidate.external_id)
            if label and row is not None:
                row.dish_kind, row.main_ingredient = label.kind, label.main_ingredient
                # Spoonacular's own dishTypes, when it had them, win.
                row.course = row.course or label.course
        session.commit()
    return [
        c.model_copy(update={
            "kind": row.dish_kind, "main_ingredient": row.main_ingredient, "course": row.course,
        })
        if (row := rows.get(c.external_id)) is not None else c
        for c in candidates
    ]


def _grocery_items(plan: Plan, skip_offer_ids: set[int] = frozenset()) -> list[GenerationItem]:
    """The plan's offers, one row each. Fridge items are not shopping, and
    regular-price purchases get their rows from `_shopping_items`."""
    return [
        GenerationItem(
            offer_id=item.offer_id,
            amount=item.quantity.amount,
            unit=item.quantity.unit,
        )
        for item in plan.grocery_list
        if item.offer_id is not None and item.offer_id not in skip_offer_ids
    ]


def _shopping_items(
    recipes: list[RecipeCache], skip_names: set[str] = frozenset()
) -> list[GenerationItem]:
    """One row per shopping name for every line that is not a pantry staple.

    The shopping list shows the rows the planned recipes use and are not
    covered by an offer (app/presenters.shopping_list); a row per name is what
    lets a tick on "carrot" be saved, and survive a refine.
    """
    names = dict.fromkeys(
        shopping_name(line.name)
        for recipe in recipes
        for line in recipe.ingredients
        if not is_pantry(line.name)
    )
    return [GenerationItem(name=name) for name in names if name not in skip_names]


def _recipes_out(generation: Generation, user: User) -> list[RecipeOut]:
    favourites = favourite_ids(user)
    return [recipe_out(recipe, generation, favourites) for recipe in generation.recipes]


@router.post("")
def generate(
    user: CurrentUser, session: SessionDep, body: GenerateRequest | None = None
) -> list[RecipeOut]:
    """The week's first plan, once per week — later changes are refines."""
    if generations_this_week(session, user, "weekly") > 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This week is already planned; ask for new recipes instead",
        )
    body = body or GenerateRequest()
    # Tags this request's agent traces in Phoenix (a no-op when tracing is off).
    with trace_context(user.id, request="weekly", meals=body.number_of_meals):
        plan, rows, verdict = _run_planner(session, user, body.number_of_meals)
    if not plan.recipes:
        # Every candidate used nothing on offer (planner.using_offers). An empty
        # week saved here would also use up the week's one weekly plan.
        raise HTTPException(
            status.HTTP_409_CONFLICT, "No recipes use this week's offers"
        )

    chosen = [rows[r.external_id] for r in plan.recipes if r.external_id in rows]
    pref = user.preference
    generation = Generation(
        user=user,
        kind="weekly",
        diet_type=pref.diet_type if pref else None,
        model="agent+critic",
        total_cost=plan.total_cost,
        # Kept even when the rounds ran out without a pass: it says what is
        # still wrong with the week.
        passed=verdict.passed,
        issues=verdict.issues,
        suggestions=verdict.suggestions,
        recipes=chosen,
        items=_grocery_items(plan) + _shopping_items(chosen),
    )
    session.add(generation)
    session.commit()
    # The week's methods, clean before anyone opens them (app/methods.py).
    prepare_methods(session, list(generation.recipes))
    log.info(
        "weekly plan %d for user %d: %s, %.2f EUR — critic %s",
        generation.id, user.id, [r.name for r in chosen], plan.total_cost or 0,
        "passed" if verdict.passed else f"not passed: {verdict.issues}",
    )
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
    # Tags this request's agent traces in Phoenix (a no-op when tracing is off).
    with trace_context(
        user.id, request="refine", mode=body.mode, count=count,
        note=body.note, pantry_items=body.pantry_items,
    ):
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
    planned_names = {
        shopping_name(line.name)
        for recipe in planned
        for line in recipe.ingredients
        if not is_pantry(line.name)
    }
    carried = [
        GenerationItem(
            offer_id=item.offer_id, name=item.name, amount=item.amount,
            unit=item.unit, checked=item.checked,
        )
        for item in current.items
        if (item.offer is not None and item.offer.canonical_ingredient_id in planned_ingredients)
        or (item.offer is None and item.name in planned_names)
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
        passed=verdict.passed,
        issues=verdict.issues,
        suggestions=verdict.suggestions,
        recipes=planned + new,
        planned_recipes=planned,
        items=carried
        + _grocery_items(plan, {i.offer_id for i in carried if i.offer_id})
        + _shopping_items(new, {i.name for i in carried if i.name}),
    )
    session.add(generation)
    session.commit()
    # The week's methods, clean before anyone opens them (app/methods.py).
    prepare_methods(session, list(generation.recipes))
    log.info(
        "refine %d for user %d (%s%s%s): kept %s, added %s — critic %s",
        generation.id, user.id, body.mode,
        f", fridge {body.pantry_items}" if body.pantry_items else "",
        f", note {body.note!r}" if body.note else "",
        [r.name for r in planned], [r.name for r in new],
        "passed" if verdict.passed else f"not passed: {verdict.issues}",
    )
    return RefineResponse(
        recipes=_recipes_out(generation, user), quota=refine_quota(session, user)
    )
