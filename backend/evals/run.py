"""Plan every frozen week for every profile, with the real agents, and measure it.

    uv run python -m evals.run                         # all fixtures × all profiles
    uv run python -m evals.run --fixture aldi-sued --profile no-pork
    uv run python -m evals.run --compare evals/results/<earlier>.json

Each run gets a fresh in-memory database built from the fixture (offer dates
moved to this week), a user with the profile's preferences and the fixture's
branch as home market, and goes through the app's own planning path
(app/routers/generate._run_planner): the filters, labelling, the planner
agent and the critic loop. Spoonacular is never asked (RECIPE_TOPUP=off);
the model is (OPENROUTER_API_KEY), so a full run costs real tokens.

Measured per run:

- outcome: planned, or the 409 the user would see and why;
- passed / rounds / open issues: the critic's verdict on the final week;
- tokens and requests per agent, and seconds;
- cost of the week, against the greedy week from the same candidates;
- variety: repeats of a dish kind or main ingredient (labels.variety_problems),
  in the week and in the greedy week;
- safety: planned recipes that break the diet, contain an allergen or a
  disliked ingredient — must be 0;
- empty meals in the week grid (calculation/schedule.py).

A report goes to evals/results/<time>.json; `--compare` prints the change
against an earlier one, by fixture and profile.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from evals.profiles import PROFILES

FIXTURES = Path(__file__).with_name("fixtures")
RESULTS = Path(__file__).with_name("results")
NUMBER_OF_MEALS = 5


def _load(session: Session, fixture: dict) -> Address:  # noqa: F821
    from cheaprecipe.db.load import STORE_NAMES
    from cheaprecipe.db.models import (
        Address,
        CanonicalIngredient,
        Cuisine,
        Offer,
        RecipeCache,
        RecipeIngredient,
        Supermarket,
    )
    from cheaprecipe.refresh import week_start

    shift = week_start() - date.fromisoformat(fixture["week_start"])
    chain = fixture["branch"]["chain"]
    branch = Address(
        supermarket=Supermarket(name=STORE_NAMES.get(chain, chain.upper())),
        market_id=fixture["branch"]["market_id"], name=fixture["branch"]["name"],
    )
    canonicals = {c["name"]: CanonicalIngredient(**c) for c in fixture["canonical_ingredients"]}
    session.add_all([branch, *canonicals.values()])

    def moved(day: str | None) -> date | None:
        return date.fromisoformat(day) + shift if day else None

    for o in fixture["offers"]:
        fields = {k: v for k, v in o.items() if k not in ("canonical", "valid_from", "valid_till")}
        session.add(Offer(address=branch, valid_from=moved(o["valid_from"]),
                          valid_till=moved(o["valid_till"]),
                          canonical_ingredient=canonicals.get(o["canonical"]), **fields))
    cuisines: dict[str, Cuisine] = {}
    for r in fixture["recipes"]:
        fields = {k: v for k, v in r.items() if k not in ("lines", "cuisine")}
        cuisine = None
        if r["cuisine"]:
            cuisine = cuisines.setdefault(r["cuisine"], Cuisine(name=r["cuisine"]))
        session.add(RecipeCache(cuisine=cuisine, **fields, ingredients=[
            RecipeIngredient(name=line["name"], amount=line["amount"], unit=line["unit"],
                             canonical_ingredient=canonicals.get(line["canonical"]))
            for line in r["lines"]
        ]))
    session.commit()
    return branch


def run_one(fixture_name: str, fixture: dict, profile_name: str, profile: dict) -> dict:
    from fastapi import HTTPException

    from app.routers import generate
    from cheaprecipe.agents import labels, loop, planner
    from cheaprecipe.calculation.allergens import allergens_of
    from cheaprecipe.calculation.diet import fits
    from cheaprecipe.calculation.schedule import build_week
    from cheaprecipe.db.adapters import allergen_free, avoids
    from cheaprecipe.db.models import User, UserPreference
    from cheaprecipe.db.session import init_db, make_engine
    from cheaprecipe.observability import usage

    engine = make_engine("sqlite://", poolclass=StaticPool)
    init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    report: dict = {"fixture": fixture_name, "profile": profile_name}

    # The candidates the loop gets, for the greedy week to compare against.
    seen: dict = {}
    real_run = loop.run

    def recording_run(candidates, offers, number_of_meals, **kwargs):
        seen.update(candidates=candidates, offers=offers, n=number_of_meals,
                    courses=kwargs.get("courses"))
        return real_run(candidates, offers, number_of_meals, **kwargs)

    loop.run = recording_run
    started = time.monotonic()
    try:
        with factory() as session, usage.counting() as spent:
            branch = _load(session, fixture)
            user = User(username=profile_name, email=f"{profile_name}@eval.test", password_hash="x",
                        preference=UserPreference(home_markets=[branch], **profile))
            session.add(user)
            session.commit()
            try:
                plan, rows, verdict, rounds = generate._run_planner(session, user, NUMBER_OF_MEALS)
            except HTTPException as exc:
                report.update(outcome=f"{exc.status_code}: {exc.detail}")
                return report
            chosen = [rows[r.external_id] for r in plan.recipes if r.external_id in rows]
    finally:
        loop.run = real_run
        report.update(seconds=round(time.monotonic() - started, 1))
    report["usage"] = spent.as_dict()

    def variety(recipes) -> list[str]:
        found = [label for label in map(labels.label_of, recipes) if label]
        return labels.variety_problems(found, [r.name for r in recipes])[0]

    greedy = planner.plan(seen["candidates"], seen["offers"], seen["n"], courses=seen["courses"])
    pref = profile
    unsafe = [
        row.name for row in chosen
        if not fits(row.diet_type, pref.get("diet_type"))
        or not allergen_free(row, set(pref.get("allergens", [])))
        or not avoids(row, pref.get("black_list", []))
        or any(allergens_of(line.name) & set(pref.get("allergens", [])) for line in row.ingredients)
    ]
    week = build_week(plan.recipes, pref.get("household_size", 1), pref.get("meal_types", ["lunch", "dinner"]))
    report.update(
        outcome="planned",
        recipes=[r.name for r in plan.recipes],
        candidates=len(seen["candidates"]),
        passed=verdict.passed,
        rounds=rounds,
        open_issues=verdict.issues if not verdict.passed else [],
        assessment=verdict.assessment,
        cost_eur=round(plan.total_cost or 0, 2),
        greedy_cost_eur=round(greedy.total_cost or 0, 2),
        variety_problems=variety(plan.recipes),
        greedy_variety_problems=variety(greedy.recipes),
        unsafe=unsafe,
        empty_meals=week.empty_slots,
        meals=len(week.slots),
    )
    return report


def _print(reports: list[dict], earlier: dict[tuple, dict]) -> None:
    head = f"{'fixture':12} {'profile':20} {'outcome':9} {'pass':5} {'rnd':3} {'tokens':>7} {'sec':>5} " \
           f"{'cost €':>7} {'greedy €':>8} {'var':>3} {'g.var':>5} {'unsafe':>6} {'empty':>7}"
    print(head)
    print("-" * len(head))
    for r in reports:
        if r.get("outcome") != "planned":
            print(f"{r['fixture'][:12]:12} {r['profile'][:20]:20} {r.get('outcome', '?')[:60]}")
            continue
        line = (f"{r['fixture'][:12]:12} {r['profile'][:20]:20} {'planned':9} {r['passed']!s:5} "
                f"{r['rounds']:3} {r['usage']['total_tokens']:7} {r['seconds']:5} {r['cost_eur']:7} "
                f"{r['greedy_cost_eur']:8} {len(r['variety_problems']):3} "
                f"{len(r['greedy_variety_problems']):5} {len(r['unsafe']):6} "
                f"{r['empty_meals']:3}/{r['meals']:<3}")
        before = earlier.get((r["fixture"], r["profile"]))
        if before and before.get("outcome") == "planned":
            line += (f"   Δ tokens {r['usage']['total_tokens'] - before['usage']['total_tokens']:+}, "
                     f"cost {r['cost_eur'] - before['cost_eur']:+.2f}, pass {before['passed']}→{r['passed']}")
        print(line)
    planned = [r for r in reports if r.get("outcome") == "planned"]
    if planned:
        print(f"\n{sum(r['passed'] for r in planned)}/{len(planned)} passed the critic; "
              f"{sum(len(r['unsafe']) for r in planned)} unsafe recipes; "
              f"{sum(r['usage']['total_tokens'] for r in planned)} tokens in all")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fixture", action="append", help="fixture name(s); default: all")
    parser.add_argument("--profile", action="append", help="profile name(s); default: all")
    parser.add_argument("--compare", type=Path, help="an earlier report; default: the latest one")
    args = parser.parse_args(argv)

    os.environ["RECIPE_TOPUP"] = "off"  # never Spoonacular: the pool is the fixture's
    os.environ["WEEKLY_REFRESH"] = "off"
    os.environ.setdefault("PHOENIX_COLLECTOR_ENDPOINT", "")
    from cheaprecipe.logging_setup import setup_logging

    setup_logging(log_file=False)

    fixtures = {p.stem: p for p in sorted(FIXTURES.glob("*.json"))}
    names = args.fixture or list(fixtures)
    missing = [n for n in names if n not in fixtures]
    if not fixtures or missing:
        print(f"no fixture {missing or ''} in {FIXTURES}; freeze one: python -m evals.freeze", file=sys.stderr)
        return 1
    profiles = {n: PROFILES[n] for n in (args.profile or PROFILES)}

    previous = args.compare or max(RESULTS.glob("*.json"), default=None)
    earlier = {}
    if previous:
        earlier = {(r["fixture"], r["profile"]): r for r in json.loads(Path(previous).read_text())["runs"]}

    reports = []
    for name in names:
        fixture = json.loads(fixtures[name].read_text())
        for profile_name, profile in profiles.items():
            print(f"… {name} / {profile_name}", file=sys.stderr, flush=True)
            reports.append(run_one(name, fixture, profile_name, profile))

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{datetime.now().astimezone():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps({"runs": reports}, ensure_ascii=False, indent=1))
    print()
    _print(reports, earlier)
    print(f"\nreport: {out}" + (f" (compared with {Path(previous).name})" if previous else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
