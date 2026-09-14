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
