"""What a long piece of work is doing right now, for whoever is listening.

Planning takes minutes; the steps it goes through (the offers, the recipe
search, each planner and critic round) are reported here, and the API's
planning jobs (app/jobs.py) listen and show them to the user. With nobody
listening, `report` does nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_listener: ContextVar[Callable[[str], None] | None] = ContextVar("progress", default=None)


@contextmanager
def listening(callback: Callable[[str], None]) -> Iterator[None]:
    token = _listener.set(callback)
    try:
        yield
    finally:
        _listener.reset(token)


def report(step: str) -> None:
    """Say what is happening now, in words a user reads ("The critic is reviewing")."""
    callback = _listener.get()
    if callback is not None:
        callback(step)
