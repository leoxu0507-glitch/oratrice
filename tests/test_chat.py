"""Deterministic provider contract tests.

This file used to be a one-off script that contacted a locally running
llama.cpp server at import time.  The default test suite must be safe on a
fresh checkout, so the transport is replaced with a tiny in-memory session.
For a real model check, see ``tests/manual_chat_smoke.py`` and run it
explicitly (it is never collected by pytest).
"""

from __future__ import annotations

from providers import ChatRequest, LlamaCppProvider


class _Response:
    status_code = 200

    def __init__(self, payload=None, *, lines=()):
        self.payload = payload
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


class _Session:
    """A requests-compatible fake; no socket is opened by this test."""

    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if kwargs.get("stream"):
            return _Response(
                lines=(
                    b'data: {"id":"offline-stream","model":"D:/AI/models/GPT-OSS-20B/GPT-OSS-20B.gguf","choices":[{"delta":{"content":"Hello"}}]}',
                    b'data: {"choices":[{"delta":{"content":" stream"},"finish_reason":"stop"}]}',
                    b"data: [DONE]",
                )
            )
        return _Response(
            {
                "id": "offline-request",
                # Simulate a transport response that reports an internal
                # model path rather than the caller's public alias.
                "model": "D:/AI/models/GPT-OSS-20B/GPT-OSS-20B.gguf",
                "choices": [
                    {
                        "message": {"content": "Hello from the fake model."},
                        "finish_reason": "stop",
                    }
                ],
            }
        )


def test_chat_script_is_offline_and_deterministic():
    session = _Session()
    provider = LlamaCppProvider(
        "http://127.0.0.1:8080",
        provider_id="local",
        session=session,
    )

    response = provider.chat(ChatRequest("gpt-oss", message="Hello, introduce yourself."))

    assert response.content == "Hello from the fake model."
    assert response.model == "gpt-oss"
    assert response.raw["model"].endswith("GPT-OSS-20B.gguf")
    assert response.provider == "local"
    assert len(session.calls) == 1
    url, kwargs = session.calls[0]
    assert url == "http://127.0.0.1:8080/v1/chat/completions"
    assert kwargs["json"]["messages"] == [
        {"role": "user", "content": "Hello, introduce yourself."}
    ]


def test_stream_exposes_request_alias_when_transport_reports_internal_model():
    session = _Session()
    provider = LlamaCppProvider(
        "http://127.0.0.1:8080",
        provider_id="local",
        session=session,
    )

    chunks = list(provider.stream(ChatRequest("gpt-oss", message="Hello.")))

    assert [chunk.content for chunk in chunks] == ["Hello", " stream"]
    assert {chunk.model for chunk in chunks} == {"gpt-oss"}
    assert chunks[0].raw["model"].endswith("GPT-OSS-20B.gguf")
