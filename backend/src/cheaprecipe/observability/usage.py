"""Model usage per agent, counted while a block of work runs.

Each agent run reports its pydantic-ai usage here (`add`). Nothing is kept
unless someone is counting — the evaluation runner (evals/run.py) wraps each
plan in `counting()` to see what it cost.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class Usage:
    requests: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    tokens: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    @property
    def total_tokens(self) -> int:
        return sum(self.tokens.values())

    def as_dict(self) -> dict:
        return {"requests": dict(self.requests), "tokens": dict(self.tokens),
                "total_tokens": self.total_tokens}


_current: ContextVar[Usage | None] = ContextVar("usage", default=None)


@contextmanager
def counting() -> Iterator[Usage]:
    usage = Usage()
    token = _current.set(usage)
    try:
        yield usage
    finally:
        _current.reset(token)


def add(agent: str, run_usage) -> None:
    """Record one agent run's usage (a pydantic-ai RunUsage), if anyone counts."""
    usage = _current.get()
    if usage is None or run_usage is None:
        return
    usage.requests[agent] += getattr(run_usage, "requests", 0) or 0
    usage.tokens[agent] += getattr(run_usage, "total_tokens", 0) or 0
