"""Agent traces to Arize Phoenix: every prompt, tool call, answer and token.

Off unless PHOENIX_COLLECTOR_ENDPOINT is set, so nothing is sent anywhere by
default and the `tracing` extra stays optional. With it on, each planner and
critic run appears in Phoenix (http://localhost:6006) as a trace: the model
request, each tool call (build_greedy_plan, price_recipe, estimate_leftovers)
with arguments and results, the critic's answer and any retries, token counts.

    uvx arize-phoenix serve                                   # the UI, port 6006
    PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006          # in .env
    uv sync --extra tracing                                   # the client side

pydantic-ai emits OpenTelemetry spans itself (Agent.instrument_all); the
OpenInference processor rewrites them into the shape Phoenix displays, which
is why it is added before the exporter — processors run in order.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext

from cheaprecipe.config import load_keys

log = logging.getLogger(__name__)

DEFAULT_PROJECT = "cheaprecipe"

_enabled = False


def _endpoint() -> str | None:
    load_keys()
    base = (os.environ.get("PHOENIX_COLLECTOR_ENDPOINT") or "").strip().rstrip("/")
    if not base:
        return None
    return base if base.endswith("/v1/traces") else f"{base}/v1/traces"


def build_provider(export_processor, project: str = DEFAULT_PROJECT):
    """A tracer provider that tags spans with the request (trace_context),
    turns pydantic-ai spans into OpenInference ones, then hands them to
    `export_processor` — in that order."""
    from openinference.instrumentation import get_attributes_from_context
    from openinference.instrumentation.pydantic_ai import OpenInferenceSpanProcessor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import SpanProcessor, TracerProvider

    class ContextAttributes(SpanProcessor):
        """Copy trace_context's user and metadata onto every span as it starts.

        OpenInference's own instrumentors read that context; pydantic-ai makes
        its spans itself, so without this the tags would never reach them.
        """

        def on_start(self, span, parent_context=None):
            span.set_attributes(dict(get_attributes_from_context()))

    provider = TracerProvider(resource=Resource.create({"openinference.project.name": project}))
    provider.add_span_processor(ContextAttributes())
    provider.add_span_processor(OpenInferenceSpanProcessor())
    provider.add_span_processor(export_processor)
    return provider


def setup_tracing() -> bool:
    """Send agent traces to Phoenix when configured; returns whether it is on."""
    global _enabled
    if _enabled:
        return True
    endpoint = _endpoint()
    if endpoint is None:
        return False
    try:
        from opentelemetry import trace
        from phoenix.otel import BatchSpanProcessor
        from pydantic_ai import Agent
        from pydantic_ai.models.instrumented import InstrumentationSettings
    except ImportError:
        log.warning(
            "PHOENIX_COLLECTOR_ENDPOINT is set but the tracing extra is not installed; "
            "run `uv sync --extra tracing`"
        )
        return False

    project = os.environ.get("PHOENIX_PROJECT_NAME") or DEFAULT_PROJECT
    provider = build_provider(BatchSpanProcessor(endpoint=endpoint), project)
    trace.set_tracer_provider(provider)
    Agent.instrument_all(InstrumentationSettings(tracer_provider=provider))

    _enabled = True
    log.info("tracing to Phoenix at %s (project %s)", endpoint, project)
    return True


def tracing_enabled() -> bool:
    return _enabled


@contextmanager
def trace_context(user_id: int | None = None, **metadata) -> Iterator[None]:
    """Tag the traces started inside with the user and request details."""
    if not _enabled:
        with nullcontext():
            yield
        return
    from openinference.instrumentation import using_attributes

    with using_attributes(
        user_id=str(user_id) if user_id is not None else None,
        metadata={key: value for key, value in metadata.items() if value is not None},
    ):
        yield
