"""M14 provider SSE completion and Core iterator ownership contracts."""

from __future__ import annotations

from threading import get_ident
from types import SimpleNamespace

import pytest

from core.ai_service import CoreFacade, CoreProviderError
from providers import (
    ChatChunk,
    ChatRequest,
    LlamaCppProvider,
    LiteLLMGatewayProvider,
    ProviderResponseError,
)
from router import RouteDecision, StaticRouter


class StreamResponse:
    status_code = 200

    def __init__(self, lines):
        self.lines = tuple(lines)
        self.closed = False
        self.chunk_sizes = []
        self.closed_thread = None

    def raise_for_status(self):
        return None

    def iter_lines(self, chunk_size=512):
        self.chunk_sizes.append(chunk_size)
        yield from self.lines

    def close(self):
        self.closed = True
        self.closed_thread = get_ident()


class StreamSession:
    def __init__(self, lines):
        self.response = StreamResponse(lines)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def _provider(factory, lines):
    session = StreamSession(lines)
    if factory is LiteLLMGatewayProvider:
        provider = factory("http://gateway", session=session, provider_id="fake")
    else:
        provider = factory("http://local", session=session, provider_id="fake")
    return provider, session


@pytest.mark.parametrize("factory", [LiteLLMGatewayProvider, LlamaCppProvider])
def test_http_sse_iterators_request_small_reads_and_close_after_terminal(factory):
    provider, session = _provider(
        factory,
        [
            b'data: {"choices":[{"delta":{"content":"first"}}]}',
            b'data: {"choices":[{"delta":{"content":"second"},"finish_reason":"stop"}]}',
            b"data: [DONE]",
        ],
    )

    chunks = list(provider.stream(ChatRequest("model.test", message="hello")))

    assert [chunk.content for chunk in chunks] == ["first", "second"]
    assert session.response.chunk_sizes == [1]
    assert session.response.closed


@pytest.mark.parametrize("factory", [LiteLLMGatewayProvider, LlamaCppProvider])
def test_http_sse_eof_without_terminal_marker_is_an_error_and_closes(factory):
    provider, session = _provider(
        factory,
        [b'data: {"choices":[{"delta":{"content":"partial"}}]}'],
    )

    stream = provider.stream(ChatRequest("model.test", message="hello"))
    assert next(stream).content == "partial"
    with pytest.raises(ProviderResponseError, match="completion marker"):
        next(stream)
    assert session.response.closed


@pytest.mark.parametrize("factory", [LiteLLMGatewayProvider, LlamaCppProvider])
def test_http_sse_finish_reason_is_a_terminal_marker_without_done(factory):
    provider, session = _provider(
        factory,
        [b'data: {"choices":[{"delta":{"content":"complete"},"finish_reason":"stop"}]}'],
    )

    chunks = list(provider.stream(ChatRequest("model.test", message="hello")))

    assert len(chunks) == 1
    assert chunks[0].finish_reason == "stop"
    assert session.response.closed


@pytest.mark.parametrize("factory", [LiteLLMGatewayProvider, LlamaCppProvider])
def test_http_sse_upstream_error_is_sanitized_and_closes(factory):
    provider, session = _provider(
        factory,
        [b'data: {"error":{"message":"secret prompt text"}}'],
    )

    with pytest.raises(ProviderResponseError, match="upstream error") as raised:
        list(provider.stream(ChatRequest("model.test", message="hello")))

    assert "secret" not in str(raised.value)
    assert session.response.closed


class ClosingProvider:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.closed = False
        self.close_thread = None

    def stream(self, request):
        try:
            yield ChatChunk("part")
            if self.fail:
                raise RuntimeError("injected stream failure")
        finally:
            self.closed = True
            self.close_thread = get_ident()


def _facade(provider):
    return CoreFacade(
        provider_instances={"provider.test": provider},
        router=StaticRouter(default=RouteDecision("model.test", "provider.test")),
        auto_start=False,
    )


@pytest.mark.parametrize("close_early", [False, True])
def test_core_closes_provider_iterator_on_completion_or_consumer_close(close_early):
    provider = ClosingProvider()
    stream = _facade(provider).stream("model.test", "hello")

    assert next(stream).content == "part"
    if close_early:
        stream.close()
    else:
        assert list(stream) == []

    assert provider.closed
    assert provider.close_thread == get_ident()


def test_core_closes_provider_iterator_after_stream_failure():
    provider = ClosingProvider(fail=True)
    stream = _facade(provider).stream("model.test", "hello")

    assert next(stream).content == "part"
    with pytest.raises(CoreProviderError):
        next(stream)

    assert provider.closed
    assert provider.close_thread == get_ident()


@pytest.mark.parametrize("provider", [
    SimpleNamespace(stream=None),
    SimpleNamespace(stream=lambda request: (_ for _ in ()).throw(NotImplementedError())),
    SimpleNamespace(
        stream=lambda request: iter(()),
        capabilities=lambda: SimpleNamespace(supports_stream=False),
    ),
])
def test_core_reports_unsupported_stream_capability(provider):
    with pytest.raises(CoreProviderError) as raised:
        list(_facade(provider).stream("model.test", "hello"))
    assert raised.value.code == "stream_unsupported"


class CloseFailureIterator:
    def __init__(self):
        self.sent = False

    def __iter__(self):
        return self

    def __next__(self):
        if self.sent:
            raise StopIteration
        self.sent = True
        return ChatChunk("part")

    def close(self):
        raise RuntimeError("secret close diagnostic")


def test_core_surfaces_a_safe_error_when_stream_close_fails():
    provider = SimpleNamespace(stream=lambda request: CloseFailureIterator())
    stream = _facade(provider).stream("model.test", "hello")

    assert next(stream).content == "part"
    with pytest.raises(CoreProviderError) as raised:
        next(stream)

    assert raised.value.code == "stream_close_error"
    assert "secret" not in str(raised.value)


@pytest.mark.parametrize("iterator_fails", [False, True])
def test_core_falls_back_to_closing_the_provider_source(iterator_fails):
    class ClosableSource:
        closed = False

        def __iter__(self):
            if iterator_fails:
                raise RuntimeError("injected iterator setup failure")
            return iter(())

        def close(self):
            self.closed = True

    source = ClosableSource()
    provider = SimpleNamespace(stream=lambda request: source)
    stream = _facade(provider).stream("model.test", "hello")

    if iterator_fails:
        with pytest.raises(CoreProviderError):
            list(stream)
    else:
        assert list(stream) == []
    assert source.closed
