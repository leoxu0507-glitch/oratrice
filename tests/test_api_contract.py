"""Fully in-process API contracts using an injected facade fake."""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from core.errors import (
    CoreConfigurationError,
    CoreHealthError,
    CoreProviderError,
    CoreRoutingError,
    CoreRuntimeError,
    CoreValidationError,
)
from core.observability import HealthReport
from providers import ChatResponse
from router import RouteDecision
from oratrice_api import create_api


class FakeFacade:
    def __init__(self) -> None:
        self.chat_calls: list[dict[str, object]] = []
        self.route_calls: list[dict[str, object]] = []
        self.health_calls: list[dict[str, object]] = []
        self.chat_error: BaseException | None = None
        self.route_error: BaseException | None = None
        self.health_error: BaseException | None = None

    def chat(self, **kwargs):
        self.chat_calls.append(dict(kwargs))
        if self.chat_error is not None:
            raise self.chat_error
        return ChatResponse(
            content="offline reply",
            model=kwargs.get("model_id"),
            provider="provider.fake",
            request_id="facade-request",
            usage={"total_tokens": 2},
            raw={"prompt": "must not escape", "cause": "transport"},
            metadata={"prompt": "must not escape", "safe": True},
        )

    def route(self, **kwargs):
        self.route_calls.append(dict(kwargs))
        if self.route_error is not None:
            raise self.route_error
        return RouteDecision(
            model=kwargs.get("model_id") or "model.fake",
            provider=kwargs.get("provider") or "provider.fake",
            task_type="chat",
            complexity="low",
            capabilities=("chat",),
            reason="offline route",
        )

    def health(self, **kwargs):
        self.health_calls.append(dict(kwargs))
        if self.health_error is not None:
            raise self.health_error
        return HealthReport(
            status="healthy",
            components={"providers": {"provider.fake": {"healthy": True}}},
            request_id=kwargs.get("request_id"),
        )


class FakeApplication:
    def __init__(self, facade: FakeFacade):
        self.facade = facade
        self.close_calls = 0

    def close(self):
        self.close_calls += 1


@pytest.fixture
def facade():
    return FakeFacade()


@pytest.fixture
def client(facade):
    application = FakeApplication(facade)
    with TestClient(
        create_api(application=application), raise_server_exceptions=False
    ) as value:
        yield value
    assert application.close_calls == 0


def test_chat_serialises_response_without_raw_cause_or_prompt(client, facade):
    response = client.post(
        "/chat",
        json={
            "model": "model.fake",
            "message": "hello",
            "temperature": 0.2,
            "max_tokens": 12,
            "metadata": {"trace": "offline"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["content"] == "offline reply"
    assert payload["provider"] == "provider.fake"
    assert "raw" not in payload
    assert "cause" not in payload
    assert "prompt" not in response.text
    assert facade.chat_calls[0]["model_id"] == "model.fake"
    assert facade.chat_calls[0]["message"] == "hello"


def test_route_calls_facade_with_uuid_and_returns_decision_only(client, facade):
    response = client.post(
        "/route",
        json={
            "model": "model.fake",
            "message": "hello",
            "capabilities": ["chat"],
            "requires_vision": False,
            "metadata": {"source": "test"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["model"] == "model.fake"
    assert payload["provider"] == "provider.fake"
    assert UUID(payload["request_id"])
    assert "content" not in payload
    assert "raw" not in payload
    assert facade.route_calls[0]["request_id"] == payload["request_id"]
    assert facade.route_calls[0]["metadata"] == {"source": "test"}


def test_health_is_always_http_200_and_has_safe_report(client, facade):
    facade.health_error = CoreHealthError(
        "health failed with prompt=secret", request_id="internal"
    )
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unhealthy"
    assert payload["healthy"] is False
    assert "secret" not in response.text
    assert "cause" not in payload


def test_request_validation_is_safe_and_forbids_extra_fields(client):
    response = client.post(
        "/chat", json={"message": "hello", "unexpected": "do-not-echo"}
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload == {"error": {"code": "validation_error", "message": "invalid request"}}
    assert "unexpected" not in response.text
    assert "hello" not in response.text


@pytest.mark.parametrize(
    "error, status",
    [
        (CoreValidationError("bad input"), 422),
        (CoreRoutingError("no route"), 422),
        (CoreProviderError("provider down", provider="provider.fake"), 502),
        (CoreRuntimeError("runtime down"), 503),
        (CoreConfigurationError("bad config"), 503),
    ],
)
def test_core_errors_map_to_stable_safe_envelopes(client, facade, error, status):
    facade.chat_error = error
    response = client.post("/chat", json={"message": "hello"})

    assert response.status_code == status
    payload = response.json()["error"]
    assert payload["code"] == error.code
    assert "cause" not in payload
    assert "hello" not in response.text


def test_unknown_errors_are_generic(client, facade):
    facade.chat_error = RuntimeError("secret prompt and stack")
    response = client.post("/chat", json={"message": "hello"})

    # TestClient must not re-raise because the API owns the final envelope.
    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "internal server error"}
    }
    assert "secret" not in response.text
    assert "hello" not in response.text
