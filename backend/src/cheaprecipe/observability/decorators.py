"""Tracing decorators wrapping agent and pipeline steps."""


def traced(name: str):
    def decorator(fn):
        return fn

    return decorator
