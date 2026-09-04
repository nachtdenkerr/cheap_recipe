"""OpenRouter client.

OpenRouter is OpenAI-wire-compatible, so we keep the `openai` SDK and only
repoint `base_url`. Models are addressed by OpenRouter slug ("<vendor>/<model>"),
which is what lets us swap vendors without touching call sites.
"""

from __future__ import annotations

import os
from functools import lru_cache

from openai import OpenAI

from cheaprecipe.config import load_keys, openrouter_api_key

BASE_URL = "https://openrouter.ai/api/v1"

DEFAULT_MODEL = "openai/gpt-4.1-mini"


@lru_cache(maxsize=1)
def get_client() -> OpenAI:
    """Shared OpenRouter client.

    OPENROUTER_API_KEY comes from keys.env. The two optional headers below are
    what OpenRouter attributes usage to on its public leaderboards.
    """
    load_keys()

    api_key = openrouter_api_key()
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set — add it to keys.env at the repo root."
        )

    headers = {}
    if referer := os.environ.get("OPENROUTER_SITE_URL"):
        headers["HTTP-Referer"] = referer
    if title := os.environ.get("OPENROUTER_APP_NAME"):
        headers["X-Title"] = title

    return OpenAI(
        base_url=BASE_URL,
        api_key=api_key,
        default_headers=headers or None,
    )


def complete(
    messages: list[dict],
    model: str = DEFAULT_MODEL,
    max_tokens: int = 1024,
    client: OpenAI | None = None,
) -> str:
    """Run one chat completion and return the assistant text.

    Chat Completions rather than the Responses API: it is the endpoint every
    OpenRouter model supports.
    """
    client = client or get_client()

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
    )
    return (response.choices[0].message.content or "").strip()
