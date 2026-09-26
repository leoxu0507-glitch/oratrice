"""High-value end-to-end facade tests using only injected in-memory fakes."""

from __future__ import annotations

import pytest

from core.ai_service import CoreFacade, CoreProviderError
from providers import ChatChunk, ChatRequest, ChatResponse
from router import RouteDecision, StaticRouter


class FakeProvider:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.chat_requests: list[ChatRequest] = []
        self.stream_requests: list[ChatRequest] = []

    def chat(self, request: ChatRequest):
        self.chat_requests.append(request)
        if self.fail:
            raise RuntimeError("fake transport failure")
        return {"content": "offline reply", "usage": {"total_tokens": 2}}

    def stream(self, request: ChatRequest):
        self.stream_requests.append(request)
        return iter((ChatChunk("off"), {"delta": "line", "finish_reason": "stop"}))


class FakeRegistry:
    def __init__(self, provider: FakeProvider):
        self.provider = provider
        self.calls: list[tuple[str, dict[str, object]]] = []

    def create(self, provider_type, config):
        self.calls.append((provider_type, dict(config)))
        return self.provider


def _facade(provider: FakeProvider, ids=("req-chat", "req-stream")):
    registry = FakeRegistry(provider)
    router = StaticRouter(default=RouteDecision("model.local", "provider.local"))
    ids_iter = iter(ids)
    facade = CoreFacade(
        provider_registry=registry,
        router=router,
        auto_start=False,
        request_id_factory=lambda: next(ids_iter),
    )
    return facade, registry


def test_chat_and_stream_share_route_identity_without_network_or_runtime():
    provider = FakeProvider()
    facade, registry = _facade(provider)

    response = facade.chat("model.local", "hello", temperature=0.1)
    chunks = list(facade.stream("model.local", "hello"))

    assert isinstance(response, ChatResponse)
    assert response.content == "offline reply"
    assert response.provider == "provider.local"
    assert response.request_id == "req-chat"
    assert response.usage == {"total_tokens": 2}
    assert [chunk.content for chunk in chunks] == ["off", "line"]
    assert all(isinstance(chunk, ChatChunk) for chunk in chunks)
    assert [chunk.provider for chunk in chunks] == ["provider.local", "provider.local"]
    assert [chunk.request_id for chunk in chunks] == [None, None]
    assert len(registry.calls) == 1
    assert provider.chat_requests[0].message == "hello"
    assert provider.chat_requests[0].temperature == 0.1
    assert provider.stream_requests[0].stream is True


def test_provider_failure_becomes_stable_core_error_with_correlation_id():
    facade, _ = _facade(FakeProvider(fail=True), ids=("req-failure",))

    with pytest.raises(CoreProviderError) as raised:
        facade.chat("model.local", "hello")

    error = raised.value
    assert error.request_id == "req-failure"
    assert error.provider == "provider.local"
    assert error.code == "provider_error"
    assert "fake transport failure" in str(error)
    assert error.to_dict()["request_id"] == "req-failure"


def test_router_cloud_fallback_is_explicitly_opt_in():
    local = RouteDecision("model.local", "provider.local")
    cloud = RouteDecision("model.cloud", "provider.cloud")
    router = StaticRouter(
        default=local,
        fallback=cloud,
        allow_cloud_fallback=True,
        local_providers={"provider.local"},
        cloud_providers={"provider.cloud"},
    )
    assert router.route({"message": "hello", "model": "model.cloud"}) == cloud
