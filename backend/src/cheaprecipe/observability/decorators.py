"""Tracing decorators wrapping agent and pipeline steps.

`traced` opens an OpenTelemetry span around a call, so steps that are not an
agent run — the planner/critic loop, the greedy planner — group their agent
runs under one parent in Phoenix. Without tracing set up (tracing.py) the
global tracer is a no-op and this costs nothing.
"""

from __future__ import annotations

import functools

from opentelemetry import trace

_tracer = trace.get_tracer("cheaprecipe")


def traced(name: str):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with _tracer.start_as_current_span(name):
                return fn(*args, **kwargs)

        return wrapper

    return decorator
