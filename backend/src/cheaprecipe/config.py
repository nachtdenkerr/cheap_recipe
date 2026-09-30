"""Environment configuration.

Keys live in `.env` at the repo root (gitignored); nothing here reads them
at import time so the modules stay importable in tests without credentials.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = REPO_ROOT / ".env"
DATA_DIR = Path(__file__).resolve().parents[2] / "data"


@lru_cache(maxsize=1)
def load_keys() -> None:
    """Load .env into the process environment (once)."""
    load_dotenv(ENV_FILE)


def openrouter_api_key() -> str | None:
    load_keys()
    return os.environ.get("OPENROUTER_API_KEY")


def spoonacular_api_key() -> str | None:
    load_keys()
    return os.environ.get("SPOONACULAR_API_KEY")


def secret_key() -> str | None:
    """Signs the API's session tokens. Unset means tokens die with the process."""
    load_keys()
    return os.environ.get("SECRET_KEY")


# Where the pipeline and the API write their log; LOG_FILE= (empty) turns it off.
DEFAULT_LOG_FILE = Path(__file__).resolve().parents[2] / "logs" / "cheaprecipe.log"


def log_level() -> str:
    load_keys()
    return os.environ.get("LOG_LEVEL", "INFO").upper()


def log_file() -> Path | None:
    load_keys()
    configured = os.environ.get("LOG_FILE")
    if configured is None:
        return DEFAULT_LOG_FILE
    return Path(configured) if configured.strip() else None
