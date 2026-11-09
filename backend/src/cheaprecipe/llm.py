"""The model client: OpenRouter, or the Neon AI Gateway.

Both are OpenAI-wire-compatible, so we keep the `openai` SDK and only repoint
`base_url`. LLM_PROVIDER picks one:

- `openrouter` (default): OPENROUTER_API_KEY, models by OpenRouter slug
  ("<vendor>/<model>").
- `neon`: the branch's AI Gateway, NEON_AI_GATEWAY_BASE_URL + _TOKEN (written
  by `neon deploy`), models by catalog id ("gpt-5-mini"). NEON_AI_MODEL
  replaces DEFAULT_MODEL there; other slugs lose their "<vendor>/" prefix.
"""

from __future__ import annotations

import logging
import os
import time
from functools import lru_cache

from openai import OpenAI

from cheaprecipe.config import load_keys, openrouter_api_key

log = logging.getLogger(__name__)

BASE_URL = "https://openrouter.ai/api/v1"

DEFAULT_MODEL = "openai/gpt-4.1-mini"
# What DEFAULT_MODEL becomes on the Neon AI Gateway, unless NEON_AI_MODEL says.
NEON_DEFAULT_MODEL = "gpt-5-mini"


def provider() -> str:
    """"neon" or "openrouter" (LLM_PROVIDER)."""
    load_keys()
    return "neon" if os.environ.get("LLM_PROVIDER", "").strip().lower() == "neon" else "openrouter"


def resolve_model(model: str) -> str:
    """The model id to send, for the provider in use."""
    if provider() != "neon":
        return model
    if model == DEFAULT_MODEL:
        return os.environ.get("NEON_AI_MODEL") or NEON_DEFAULT_MODEL
    return model.split("/", 1)[-1]


def neon_gateway() -> tuple[str, str]:
    """The AI Gateway's OpenAI-compatible base URL (/v1) and its token."""
    load_keys()
    base = os.environ.get("NEON_AI_GATEWAY_BASE_URL")
    token = os.environ.get("NEON_AI_GATEWAY_TOKEN")
    if not base or not token:
        raise RuntimeError(
            "NEON_AI_GATEWAY_BASE_URL / NEON_AI_GATEWAY_TOKEN are not set — run `neon deploy`."
        )
    # The variable is the bare branch host; /v1 is the chat-completions dialect.
    return f"{base.rstrip('/')}/v1", token


@lru_cache(maxsize=1)
def get_client() -> OpenAI:
    """Shared client: the Neon AI Gateway when LLM_PROVIDER=neon, else OpenRouter.

    OPENROUTER_API_KEY comes from .env. The two optional headers below are
    what OpenRouter attributes usage to on its public leaderboards.
    """
    load_keys()

    if provider() == "neon":
        base_url, token = neon_gateway()
        return OpenAI(base_url=base_url, api_key=token)

    api_key = openrouter_api_key()
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set — add it to .env at the repo root."
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

    model = resolve_model(model)
    started = time.perf_counter()
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
    )
    elapsed = time.perf_counter() - started
    choice = _log_response(response, model, max_tokens, elapsed)

    return (choice.message.content or "").strip()


def _log_response(response, model: str, max_tokens: int, elapsed: float):
    """Report timing, token use and truncation; return the first choice."""
    usage = getattr(response, "usage", None)
    log.debug(
        "%s completed in %.2fs (prompt=%s, completion=%s tokens)",
        model,
        elapsed,
        getattr(usage, "prompt_tokens", "?"),
        getattr(usage, "completion_tokens", "?"),
    )

    choice = response.choices[0]
    if choice.finish_reason == "length":
        # A truncated response is the usual cause of dropped batch records
        # downstream, and nothing else surfaces it.
        log.warning(
            "%s hit the %d-token cap — the response is truncated", model, max_tokens
        )
    return choice
