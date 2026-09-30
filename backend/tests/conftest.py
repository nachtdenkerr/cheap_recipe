"""Shared test setup: no test reaches Spoonacular.

The API tops up the recipe pool from Spoonacular when a user runs short
(cheaprecipe/refresh.py), and a developer's .env holds a real key — so without
this, a test with a small pool would spend real quota. Tests that exercise a
fetch stub `retrieval.complex_search` (or `requests.get`) themselves.
"""

import pytest
from pydantic_ai import models

from cheaprecipe.matching import retrieval


@pytest.fixture(autouse=True)
def no_spoonacular(monkeypatch):
    def refuse(url, *args, **kwargs):
        raise RuntimeError(f"network disabled in tests: {url}")

    # At the HTTP call, so tests that stub requests.get themselves still can.
    monkeypatch.setattr(retrieval.requests, "get", refuse)
    # No test starts a real weekly refresh (offers fetch + LLM) by accident;
    # the scheduler's own tests switch it back on.
    monkeypatch.setenv("WEEKLY_REFRESH", "off")
    # Nor a real model: a test drives an agent with FunctionModel, or not at all.
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)
