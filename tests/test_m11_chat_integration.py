"""M11 HTTP -> facade -> canonical provider tests, without model/network IO."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.ai_service import CoreFacade
from core.errors import CoreValidationError
from oratrice_api import create_api
from oratrice_api.app import _ChatBodyLimit
from oratrice_api.conversation import MAX_CHAT_BODY_BYTES, MAX_CONTEXT_BYTES, MESSAGE_OVERHEAD_BYTES
from providers import ChatRequest, ChatResponse
from router import RouteDecision


class RecordingRouter:
    def __init__(self):
        self.requests = []

    def route(self, request):
        self.requests.append(request)
        return RouteDecision(model="model.test", provider="provider.test")


class RecordingProvider:
    def __init__(self):
        self.requests = []
        self.fail = False

    def chat(self, request: ChatRequest):
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("upstream unavailable")
        return ChatResponse(content="Return a + b adds the two arguments.", model=request.model)


def make_client():
    provider = RecordingProvider()
    router = RecordingRouter()
    facade = CoreFacade(
        provider_instances={"provider.test": provider}, router=router, auto_start=False,
    )
    return TestClient(create_api(application=SimpleNamespace(facade=facade))), facade, router, provider


def test_followup_reaches_provider_with_roles_and_router_with_context():
    client, _, router, provider = make_client()
    with client:
        first = client.post("/chat", json={"message": "Explain def add(a, b): return a + b", "history": []})
        assert first.status_code == 200
        history = [
            {"role": "user", "content": "Explain def add(a, b): return a + b"},
            {"role": "assistant", "content": first.json()["content"]},
        ]
        followup = client.post("/chat", json={"message": "Continue explaining that code.", "history": history})
        assert followup.status_code == 200
    payload = provider.requests[-1].to_payload()
    assert payload["messages"] == [*history, {"role": "user", "content": "Continue explaining that code."}]
    assert payload["max_tokens"] == 256
    assert "history" not in payload
    assert "def add(a, b)" in router.requests[-1].message
    assert "Continue explaining" in router.requests[-1].message
    assert "user:" in router.requests[-1].message
    assert "messages" not in followup.json()


def test_legacy_single_message_keeps_generation_options_and_reset_has_no_server_history():
    client, _, _, provider = make_client()
    with client:
        assert client.post("/chat", json={"message": "Legacy", "max_tokens": 19}).status_code == 200
        assert provider.requests[-1].max_tokens == 19
        assert client.post("/chat", json={"message": "New conversation", "history": []}).status_code == 200
    assert provider.requests[-1].to_payload()["messages"] == [{"role": "user", "content": "New conversation"}]


def test_context_error_never_routes_and_does_not_poison_next_request():
    client, _, router, provider = make_client()
    with client:
        rejected = client.post("/chat", json={"message": "x" * (MAX_CONTEXT_BYTES + 1), "history": []})
        assert rejected.status_code == 422
        assert rejected.json()["error"]["code"] == "context_limit"
        assert router.requests == []
        assert provider.requests == []
        assert client.post("/chat", json={"message": "Recovered", "history": []}).status_code == 200


def test_upstream_failure_releases_admission_and_does_not_store_any_history():
    client, _, _, provider = make_client()
    with client:
        provider.fail = True
        failed = client.post("/chat", json={"message": "Fails", "history": []})
        assert failed.status_code == 502
        provider.fail = False
        assert client.post("/chat", json={"message": "Recovered", "history": []}).status_code == 200
    assert provider.requests[-1].to_payload()["messages"] == [{"role": "user", "content": "Recovered"}]


def test_body_limit_rejects_before_json_parsing_and_facade_access():
    client, _, router, provider = make_client()
    with client:
        response = client.post("/chat", content=b"!" * (MAX_CHAT_BODY_BYTES + 1))
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "request_too_large"
        assert "!!!" not in response.text
        assert client.get("/live").status_code == 200
    assert router.requests == []
    assert provider.requests == []


def test_chunked_body_cannot_bypass_limit_with_missing_or_small_content_length():
    async def exercise(headers):
        sent, called = [], []
        events = iter([
            {"type": "http.request", "body": b"x" * MAX_CHAT_BODY_BYTES, "more_body": True},
            {"type": "http.request", "body": b"x", "more_body": False},
        ])

        async def receive():
            return next(events)

        async def send(event):
            sent.append(event)

        async def downstream(scope, receive, send):
            called.append(True)

        await _ChatBodyLimit(downstream)(
            {"type": "http", "method": "POST", "path": "/chat", "headers": headers}, receive, send,
        )
        assert not called
        assert sent[0]["status"] == 413

    asyncio.run(exercise([]))
    asyncio.run(exercise([(b"content-length", b"1")]))


def test_exact_body_boundary_replays_all_bytes_and_small_messages_stay_compatible():
    async def exercise():
        observed = []
        events = iter([{"type": "http.request", "body": b"x" * MAX_CHAT_BODY_BYTES, "more_body": False}])

        async def receive():
            return next(events)

        async def downstream(scope, replay, send):
            observed.append(await replay())

        async def send(event):
            raise AssertionError("the accepted request must not receive a rejection")

        await _ChatBodyLimit(downstream)(
            {"type": "http", "method": "POST", "path": "/chat", "headers": []}, receive, send,
        )
        assert observed == [{"type": "http.request", "body": b"x" * MAX_CHAT_BODY_BYTES, "more_body": False}]

    asyncio.run(exercise())


def test_context_exact_boundary_is_accepted_without_silent_truncation():
    client, _, _, provider = make_client()
    message = "a" * (MAX_CONTEXT_BYTES - MESSAGE_OVERHEAD_BYTES)
    with client:
        assert client.post("/chat", json={"message": message, "history": []}).status_code == 200
    assert provider.requests[-1].messages[-1].content == message


@pytest.mark.parametrize("history", [[{"role": "assistant", "content": "orphan"}], [1, 2]])
def test_facade_rejects_bad_history_before_routing(history):
    _, facade, router, provider = make_client()
    with pytest.raises(CoreValidationError):
        facade.chat(message="hello", history=history)
    assert not router.requests and not provider.requests
