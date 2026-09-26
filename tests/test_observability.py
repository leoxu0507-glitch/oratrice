from __future__ import annotations

import logging

from core.ai_service import CoreFacade, CoreProviderError
from core.observability import HealthReport, StructuredLogger, get_request_id, redact, request_context
from providers.base import ChatResponse, ProviderHealth
from router.contracts import RouteDecision


class _Router:
    def route(self, request):
        return RouteDecision(model=request.model or "demo", provider="fake", reason="test")


class _Provider:
    def chat(self, request):
        return ChatResponse(content="ok", model=request.model)

    def stream(self, request):
        return iter(())

    def health(self):
        return ProviderHealth(status="healthy", provider="fake")

    def models(self):
        return []


def test_redaction_removes_credentials_and_message_payloads():
    safe = redact({"api_key": "secret", "Authorization": "Bearer abc", "prompt": "do not log", "provider": "fake"})
    assert safe["api_key"] == "[REDACTED]"
    assert safe["Authorization"] == "[REDACTED]"
    assert safe["prompt"] == "[REDACTED]"
    assert safe["provider"] == "fake"


def test_request_context_correlates_structured_events_without_prompt():
    events = []
    logger = StructuredLogger(logging.getLogger("oratrice.test"), sink=events.append)
    with request_context("req-1"):
        assert get_request_id() == "req-1"
        logger.info("request.started", prompt="private", provider="fake")
    assert events[0]["request_id"] == "req-1"
    assert events[0]["prompt"] == "[REDACTED]"


def test_core_facade_health_aggregates_provider_and_correlation_id():
    facade = CoreFacade(
        router=_Router(),
        provider_instances={"fake": _Provider()},
        auto_start=False,
        request_id_factory=lambda: "health-1",
    )
    report = facade.health()
    assert isinstance(report, HealthReport)
    assert report.request_id == "health-1"
    assert report.healthy
    assert report["providers"]["fake"]["healthy"]


def test_provider_failure_keeps_cause_and_request_id():
    class Bad(_Provider):
        def chat(self, request):
            raise RuntimeError("transport failed")

    facade = CoreFacade(
        router=_Router(),
        provider_instances={"fake": Bad()},
        auto_start=False,
        request_id_factory=lambda: "req-2",
    )
    try:
        facade.chat("demo", "hello")
    except CoreProviderError as exc:
        assert exc.request_id == "req-2"
        assert isinstance(exc.cause, RuntimeError)
    else:
        raise AssertionError("provider failure should cross the core boundary")
