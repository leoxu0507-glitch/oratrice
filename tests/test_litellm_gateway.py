from __future__ import annotations

import pytest

from providers import (
    ChatChunk,
    ChatRequest,
    ChatResponse,
    LiteLLMGatewayProvider,
    ProviderTimeoutError,
    ProviderUnavailableError,
)


class FakeResponse:
    def __init__(self, payload=None, *, status_code=200, lines=()):
        self.payload = payload
        self.status_code = status_code
        self.lines = tuple(lines)
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload

    def iter_lines(self):
        return iter(self.lines)

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        if url.endswith("/health"):
            return FakeResponse({"status": "healthy"})
        return FakeResponse({"data": [{"id": "gateway/model"}]})

    def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        if kwargs.get("stream"):
            return FakeResponse(
                lines=(
                    b'data: {"id":"r","model":"gateway/model","choices":[{"delta":{"content":"he"}}]}',
                    b'data: {"choices":[{"delta":{"content":"llo"},"finish_reason":"stop"}]}',
                    b"data: [DONE]",
                )
            )
        return FakeResponse(
            {
                "id": "r",
                "model": "gateway/model",
                "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 2},
            }
        )


def test_gateway_normalizes_chat_stream_health_and_auth_without_network():
    session = FakeSession()
    provider = LiteLLMGatewayProvider(
        "http://gateway:4000",
        provider_id="gateway",
        api_key="resolved-master-key",
        model_map={"assistant": "configured/upstream-model"},
        session=session,
    )

    response = provider.chat(ChatRequest("assistant", message="hi"))
    assert isinstance(response, ChatResponse)
    assert response.content == "hello"
    assert response.model == "assistant"
    assert response.raw["model"] == "gateway/model"
    assert response.provider == "gateway"
    assert response.usage["total_tokens"] == 2
    assert session.calls[0][1] == "http://gateway:4000/v1/chat/completions"
    assert session.calls[0][2]["json"]["model"] == "configured/upstream-model"
    assert session.calls[0][2]["headers"]["Authorization"] == "Bearer resolved-master-key"

    chunks = list(provider.stream(ChatRequest("assistant", message="hi")))
    assert all(isinstance(item, ChatChunk) for item in chunks)
    assert "".join(item.content for item in chunks) == "hello"
    assert {item.model for item in chunks} == {"assistant"}
    assert chunks[0].raw["model"] == "gateway/model"
    assert chunks[-1].finish_reason == "stop"
    assert provider.health().healthy
    assert provider.models()["data"][0]["id"] == "gateway/model"

    # Legacy calls retain the historical string shape.
    assert provider.chat("assistant", "hi") == "hello"
    assert list(provider.stream("assistant", "hi"))[:2] == ["he", "llo"]


def test_gateway_accepts_provider_config_mapping_and_never_expands_env(monkeypatch):
    monkeypatch.setenv("LITELLM_MASTER_KEY", "must-not-be-read")
    session = FakeSession()
    provider = LiteLLMGatewayProvider(
        {
            "id": "configured-gateway",
            "type": "litellm",
            "base_url": "http://gateway:4000/v1",
            # ConfigurationLoader resolves this before adapter construction.
            "api_key": "already-resolved",
            "models": {"assistant": "configured/model"},
            "session": session,
        }
    )
    provider.chat(ChatRequest("assistant", message="hi"))
    assert session.calls[0][1] == "http://gateway:4000/v1/chat/completions"
    assert session.calls[0][2]["headers"]["Authorization"] == "Bearer already-resolved"


@pytest.mark.parametrize(
    "status,expected",
    [(503, ProviderUnavailableError), (504, ProviderUnavailableError)],
)
def test_gateway_maps_server_failures_to_retryable_unavailable(status, expected):
    class ErrorSession:
        def post(self, url, **kwargs):
            return FakeResponse({}, status_code=status)

    provider = LiteLLMGatewayProvider("http://gateway", session=ErrorSession())
    with pytest.raises(expected) as raised:
        provider.chat(ChatRequest("assistant", message="hi"))
    assert raised.value.retryable


def test_gateway_maps_transport_timeout_without_exposing_credentials():
    class TimeoutSession:
        def post(self, url, **kwargs):
            raise TimeoutError("request included Bearer secret-but-never-logged")

    provider = LiteLLMGatewayProvider(
        "http://gateway", api_key="secret-but-never-logged", session=TimeoutSession()
    )
    with pytest.raises(ProviderTimeoutError) as raised:
        provider.chat(ChatRequest("assistant", message="hi"))
    assert "secret-but-never-logged" not in str(raised.value)
