"""Every shown recipe's method: fetched if missing, edited once into clean steps.

Two steps, each allowed to fail without failing the request — a recipe
without clean steps is still a recipe:

1. db/load.fill_instructions — Spoonacular, for recipes stored without a
   method (fetched before the search asked for one);
2. db/load.check_methods — the method editor (agents/method.py), once per
   recipe, for methods not yet checked.

Run for the recipes a plan chose, while planning (which takes a while
anyway), and for whatever is shown still unchecked.
"""

import logging

from pydantic_ai.exceptions import AgentRunError
from sqlalchemy.orm import Session

from cheaprecipe.db import load
from cheaprecipe.db.models import RecipeCache

log = logging.getLogger(__name__)


def prepare_methods(session: Session, recipes: list[RecipeCache]) -> None:
    if not any(not r.instructions or not r.method_checked for r in recipes):
        return
    try:
        load.fill_instructions(session, recipes)
    except Exception as exc:  # noqa: BLE001 — network, quota: no method yet
        session.rollback()
        log.warning("could not fetch the method of %d recipes: %s", len(recipes), exc)
    try:
        load.check_methods(session, recipes)
    except (RuntimeError, AgentRunError) as exc:  # no key, provider down, bad answers
        session.rollback()
        log.warning("could not edit the method of %d recipes: %s", len(recipes), exc)
