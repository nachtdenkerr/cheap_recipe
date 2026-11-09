"""The Neon service seams: the model provider switch and the offers archive."""

from datetime import date

import pandas as pd

from cheaprecipe import llm, storage
from cheaprecipe.agents import planner


def test_openrouter_is_the_default_provider(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert llm.provider() == "openrouter"
    assert llm.resolve_model(llm.DEFAULT_MODEL) == llm.DEFAULT_MODEL


def test_the_neon_gateway_gets_catalog_model_ids(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "neon")
    monkeypatch.delenv("NEON_AI_MODEL", raising=False)
    assert llm.resolve_model(llm.DEFAULT_MODEL) == llm.NEON_DEFAULT_MODEL
    assert llm.resolve_model("anthropic/claude-haiku-4-5") == "claude-haiku-4-5"
    monkeypatch.setenv("NEON_AI_MODEL", "gpt-5-4-mini")
    assert llm.resolve_model(llm.DEFAULT_MODEL) == "gpt-5-4-mini"


def test_the_gateway_client_points_at_the_branch(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "neon")
    monkeypatch.setenv("NEON_AI_GATEWAY_BASE_URL", "https://br-x-api.ai.test/")
    monkeypatch.setenv("NEON_AI_GATEWAY_TOKEN", "nt_live_test")
    llm.get_client.cache_clear()
    planner.chat_model.cache_clear()
    try:
        client = llm.get_client()
        assert str(client.base_url) == "https://br-x-api.ai.test/v1/"
        assert client.api_key == "nt_live_test"
        assert planner.chat_model(llm.DEFAULT_MODEL).model_name == llm.NEON_DEFAULT_MODEL
    finally:
        llm.get_client.cache_clear()
        planner.chat_model.cache_clear()


def test_the_offers_archive_is_keyed_by_branch_and_week(monkeypatch):
    uploads = {}
    monkeypatch.setattr(storage, "enabled", lambda: True)
    monkeypatch.setattr(storage, "put", lambda key, body, ctype: uploads.update({key: (body, ctype)}))
    frame = pd.DataFrame({"title": ["Grana Padano"], "price": [1.99]})

    key = storage.archive_offers(frame, "edeka", "10001604", date(2026, 11, 9))

    assert key == "offers/edeka/10001604/2026-11-09.csv"
    body, ctype = uploads[key]
    assert body.decode().splitlines() == ["title,price", "Grana Padano,1.99"]
    assert ctype.startswith("text/csv")


def test_a_failed_upload_never_stops_the_refresh(monkeypatch):
    monkeypatch.setattr(storage, "enabled", lambda: True)

    def broken(*_args):
        raise ConnectionError("bucket unreachable")

    monkeypatch.setattr(storage, "put", broken)
    assert storage.archive_offers(pd.DataFrame({"a": [1]}), "aldi", "x", date(2026, 11, 9)) is None


def test_no_archive_without_storage():
    # conftest switches storage off for every test.
    assert storage.archive_offers(pd.DataFrame({"a": [1]}), "aldi", "x", date(2026, 11, 9)) is None
