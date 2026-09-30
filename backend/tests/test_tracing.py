"""Tracing wiring: off by default, and agent runs become OpenInference spans."""

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.instrumented import InstrumentationSettings

from cheaprecipe.observability import tracing


def test_tracing_is_off_without_an_endpoint(monkeypatch):
    monkeypatch.delenv("PHOENIX_COLLECTOR_ENDPOINT", raising=False)
    monkeypatch.setattr(tracing, "load_keys", lambda: None)  # ignore a local .env
    assert tracing.setup_tracing() is False
    with tracing.trace_context(user_id=1, request="refine"):
        pass  # a no-op, not an error


def test_the_endpoint_gets_the_traces_path(monkeypatch):
    monkeypatch.setattr(tracing, "load_keys", lambda: None)
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006/")
    assert tracing._endpoint() == "http://localhost:6006/v1/traces"


def test_an_agent_run_is_exported_as_openinference_spans():
    pytest.importorskip("openinference.instrumentation.pydantic_ai")
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exported = InMemorySpanExporter()
    provider = tracing.build_provider(SimpleSpanProcessor(exported), project="test")

    def answer(messages, info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"value": 3})])

    from pydantic import BaseModel

    class Out(BaseModel):
        value: int

    # The same switch setup_tracing uses; undone so other tests are not traced.
    Agent.instrument_all(InstrumentationSettings(tracer_provider=provider))
    try:
        agent = Agent(FunctionModel(answer), output_type=Out)
        tracing._enabled = True  # as setup_tracing leaves it
        with tracing.trace_context(user_id=42, request="refine"):
            assert agent.run_sync("give me three").output.value == 3
    finally:
        Agent.instrument_all(False)
        tracing._enabled = False

    spans = exported.get_finished_spans()
    assert spans, "the run produced no spans"
    kinds = {span.attributes.get("openinference.span.kind") for span in spans}
    # The processor ran before export: Phoenix sees agent and LLM spans.
    assert "AGENT" in kinds or "LLM" in kinds
    assert all(span.resource.attributes["openinference.project.name"] == "test" for span in spans)
    # trace_context's tags reach pydantic-ai's own spans.
    assert all(span.attributes.get("user.id") == "42" for span in spans)
    assert all("refine" in (span.attributes.get("metadata") or "") for span in spans)
