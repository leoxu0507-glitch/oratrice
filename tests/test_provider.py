from __future__ import annotations

from providers import (
    ChatChunk,
    ChatRequest,
    ChatResponse,
    LlamaCppProvider,
    ProviderRegistry,
    create_default_registry,
)


class FakeResponse:
    status_code = 200

    def __init__(self, payload=None, lines=()):
        self.payload = payload if payload is not None else {}
        self.lines = tuple(lines)
        self.closed = False

    def raise_for_status(self):
        return None

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
        return FakeResponse({"status": "ok"})

    def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        if kwargs.get("stream"):
            return FakeResponse(
                lines=(
                    b'data: {"choices":[{"delta":{"content":"he"}}]}',
                    b'data: {"choices":[{"delta":{"content":"llo"},"finish_reason":"stop"}]}',
                    b"data: [DONE]",
                )
            )
        return FakeResponse(
            {
                "id": "req-1",
                "model": "demo",
                "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 2},
            }
        )


def test_llama_adapter_supports_canonical_and_legacy_calls_without_network():
    session = FakeSession()
    provider = LlamaCppProvider("http://127.0.0.1:8080", session=session, provider_id="local")

    response = provider.chat(ChatRequest("demo", message="hi"))
    assert isinstance(response, ChatResponse)
    assert response.content == "hello"
    assert provider.chat("demo", "hi") == "hello"

    chunks = list(provider.stream(ChatRequest("demo", message="hi")))
    assert all(isinstance(item, ChatChunk) for item in chunks)
    assert "".join(item.content for item in chunks) == "hello"
    assert list(provider.stream("demo", "hi")) == ["he", "llo"]
    assert provider.health().healthy
    assert session.calls


def test_default_registry_is_explicit_and_constructs_only_on_create():
    registry = create_default_registry()
    assert registry.has("llama-cpp")
    assert not registry.has("requests")
    session = FakeSession()
    provider = registry.create(
        "openai-compatible",
        {"base_url": "http://127.0.0.1:8080", "provider_id": "local", "session": session},
    )
    assert isinstance(provider, LlamaCppProvider)
    assert session.calls == []


def test_registry_rejects_duplicate_names_and_unknown_factories():
    registry = ProviderRegistry()
    registry.register("fake", lambda config: object())
    try:
        registry.register("fake", lambda config: object())
    except Exception as exc:
        assert "already registered" in str(exc)
    else:
        raise AssertionError("duplicate registration should fail")
