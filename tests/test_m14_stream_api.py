"""M14 streaming API contracts without providers, sockets, or model weights."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Event, Lock, get_ident
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from core.errors import CoreProviderError
from oratrice_api import create_api
from oratrice_api.conversation import MAX_CHAT_BODY_BYTES, MAX_CONTEXT_BYTES
from oratrice_api.streaming import BoundedSSEStreamingResponse, StreamSession, _json_sse
from providers import ChatChunk, ChatResponse


def _events(text: str):
    result = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        name = None
        data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if name is not None:
            result.append((name, data))
    return result


class RecordingFacade:
    def __init__(self):
        self.stream_calls = []
        self.chat_calls = []
        self.route_calls = []
        self.chat_entered = Event()
        self.chat_release = Event()
        self.stream_entered = Event()
        self.stream_release = Event()
        self.block_stream = False
        self.stream_thread_ids = []
        self.fail = False

    def stream(self, **kwargs):
        self.stream_calls.append(kwargs)
        self.stream_thread_ids.append(get_ident())
        self.stream_entered.set()
        yield ChatChunk(content="Hello ")
        if self.block_stream:
            self.stream_release.wait(timeout=2)
        yield ChatChunk(content="world", finish_reason="stop")
        if self.fail:
            raise CoreProviderError("private provider details and secret must not leak")

    def chat(self, **kwargs):
        self.chat_calls.append(kwargs)
        self.chat_entered.set()
        self.chat_release.wait(timeout=2)
        return ChatResponse(content="ordinary reply")

    def route(self, **kwargs):
        self.route_calls.append(kwargs)
        return SimpleNamespace(model="model.test", provider="provider.test")


def _client(facade=None):
    current = facade or RecordingFacade()
    return TestClient(create_api(application=SimpleNamespace(facade=current)), raise_server_exceptions=False), current


def test_stream_is_additive_and_emits_safe_ordered_events_with_capped_request():
    client, facade = _client()
    with client:
        response = client.post("/chat/stream", json={
            "message": "Continue.",
            "history": [{"role": "user", "content": "First?"}, {"role": "assistant", "content": "Yes."}],
        })
        facade.chat_release.set()
        legacy = client.post("/chat", json={"message": "ordinary"})
    events = _events(response.text)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert events[0][0] == "start"
    assert events[0][1]["version"] == 1
    assert events[0][1]["cancellation"] == "stop_wait_only"
    assert events[0][1]["request_id"]
    assert [kind for kind, _ in events] == ["start", "delta", "delta", "complete"]
    assert "".join(data["text"] for kind, data in events if kind == "delta") == "Hello world"
    assert events[-1] == ("complete", {"finish_reason": "stop"})
    assert facade.stream_calls[0]["message"] == "Continue."
    assert facade.stream_calls[0]["history"] == [
        {"role": "user", "content": "First?"},
        {"role": "assistant", "content": "Yes."},
    ]
    assert facade.stream_calls[0]["max_tokens"] == 256
    assert facade.stream_thread_ids[0] != get_ident()
    assert "content-length" not in response.headers
    assert legacy.status_code == 200
    assert legacy.json()["content"] == "ordinary reply"


def test_stream_limit_or_validation_rejects_before_admission_or_provider():
    client, facade = _client()
    with client:
        oversized = client.post("/chat/stream", content=b"x" * (MAX_CHAT_BODY_BYTES + 1))
        invalid_context = client.post("/chat/stream", json={"message": "x" * MAX_CONTEXT_BYTES, "history": []})
        too_many_tokens = client.post("/chat/stream", json={"message": "hello", "max_tokens": 257})
    assert oversized.status_code == 413
    assert oversized.json()["error"]["code"] == "request_too_large"
    assert invalid_context.status_code == 422
    assert invalid_context.json()["error"]["code"] == "context_limit"
    assert too_many_tokens.status_code == 422
    assert too_many_tokens.json()["error"]["code"] == "invalid_stream_request"
    assert facade.stream_calls == []


def test_missing_stream_port_is_explicit_and_keeps_legacy_chat_available():
    facade = SimpleNamespace(chat=lambda **kwargs: ChatResponse(content="legacy"))
    client, _ = _client(facade)
    with client:
        unsupported = client.post("/chat/stream", json={"message": "hello"})
        ordinary = client.post("/chat", json={"message": "hello"})
    assert unsupported.status_code == 501
    assert unsupported.json()["error"]["code"] == "stream_unsupported"
    assert ordinary.status_code == 200


def test_stream_failure_is_terminal_safe_error_without_provider_details():
    facade = RecordingFacade()
    facade.fail = True
    client, _ = _client(facade)
    with client:
        response = client.post("/chat/stream", json={"message": "hello"})
    events = _events(response.text)
    assert [kind for kind, _ in events] == ["start", "delta", "delta", "error"]
    payload = events[-1][1]
    assert payload["error"]["code"] == "upstream_error"
    assert "private provider details" not in response.text
    assert "secret" not in response.text
    assert payload["error"]["request_id"] == events[0][1]["request_id"]
    assert payload["work_may_continue"] is True


def test_chat_and_route_return_busy_while_stream_worker_owns_admission():
    for blocked_operation in ("chat", "route"):
        facade = RecordingFacade()
        facade.block_stream = True
        client, _ = _client(facade)
        stream_done = Event()

        def consume_stream():
            with client.stream("POST", "/chat/stream", json={"message": "stream"}) as response:
                assert response.status_code == 200
                list(response.iter_bytes())
            stream_done.set()

        with ThreadPoolExecutor(max_workers=1) as pool, client:
            pending = pool.submit(consume_stream)
            assert facade.stream_entered.wait(timeout=1)
            busy = client.post("/" + blocked_operation, json={"message": blocked_operation})
            assert busy.status_code == 503
            assert busy.headers["retry-after"] == "1"
            assert busy.json()["error"]["code"] == blocked_operation + "_busy"
            facade.stream_release.set()
            pending.result(timeout=2)
            assert stream_done.is_set()


def test_disconnect_stops_delivery_but_iterator_cleanup_owns_admission_until_end():
    entered, release, closed = Event(), Event(), Event()
    admission = Lock()
    assert admission.acquire(blocking=False)

    class BlockingFacade:
        def stream(self, **kwargs):
            try:
                yield ChatChunk(content="first")
                entered.set()
                release.wait(timeout=2)
                yield ChatChunk(content="after stop")
            finally:
                closed.set()

    session = StreamSession(BlockingFacade(), admission, "req-test", None, "hello", {}, queue_poll_seconds=0.001)
    session.start()

    async def disconnect_after_first_delta():
        events = session.events()
        assert _events((await events.__anext__()).decode())[0][0] == "start"
        assert _events((await events.__anext__()).decode())[0][0] == "delta"
        assert entered.wait(timeout=1)
        session.stop_delivery("disconnect")
        await events.aclose()

    asyncio.run(disconnect_after_first_delta())
    assert admission.locked()
    assert not closed.is_set()
    release.set()
    assert session._finished.wait(timeout=1)
    assert closed.is_set()
    assert not admission.locked()


def test_delivery_deadline_and_slow_queue_bound_stop_output_but_drain_worker():
    entered, release, closed = Event(), Event(), Event()
    admission = Lock()
    admission.acquire()

    class BlockingFacade:
        def stream(self, **kwargs):
            try:
                entered.set()
                release.wait(timeout=2)
                yield ChatChunk(content="large pending output")
                for _ in range(10):
                    yield ChatChunk(content="more")
            finally:
                closed.set()

    session = StreamSession(
        BlockingFacade(), admission, "req-timeout", None, "hello", {},
        max_queued_events=1, queue_wait_seconds=0.02, delivery_seconds=0.02,
        queue_poll_seconds=0.001, producer_poll_seconds=0.001,
    )
    session.start()

    async def read_until_cancelled():
        return [block async for block in session.events()]

    events = _events(b"".join(asyncio.run(read_until_cancelled())).decode())
    assert events[0][0] == "start"
    assert events[-1] == ("cancelled", {"reason": "timeout", "work_may_continue": True})
    assert entered.is_set()
    assert admission.locked()
    assert not closed.is_set()
    release.set()
    assert session._finished.wait(timeout=1)
    assert closed.is_set()
    assert not admission.locked()


def test_slow_consumer_queue_is_bounded_and_producer_drains_after_stop():
    admission = Lock()
    admission.acquire()
    entered, closed = Event(), Event()

    class FastFacade:
        def stream(self, **kwargs):
            try:
                entered.set()
                for _ in range(100):
                    yield ChatChunk(content="one")
            finally:
                closed.set()

    session = StreamSession(
        FastFacade(), admission, "req-slow", None, "hello", {},
        max_queued_events=1, queue_wait_seconds=0.01, delivery_seconds=5,
        queue_poll_seconds=0.001, producer_poll_seconds=0.001,
    )
    session.start()
    assert entered.wait(timeout=1)
    assert session._finished.wait(timeout=1)
    assert session._queue.qsize() <= 1
    assert closed.is_set()
    assert not admission.locked()

    async def read_terminal():
        return [block async for block in session.events()]

    events = _events(b"".join(asyncio.run(read_terminal())).decode())
    assert events[0][0] == "start"
    assert events[-1] == ("cancelled", {"reason": "slow_consumer", "work_may_continue": True})


def test_asgi_header_send_timeout_returns_promptly_and_keeps_worker_owned_slot():
    admission = Lock()
    admission.acquire()
    entered, release, closed = Event(), Event(), Event()

    class BlockingFacade:
        def stream(self, **kwargs):
            try:
                entered.set()
                release.wait(timeout=2)
                yield ChatChunk(content="after blocked header")
            finally:
                closed.set()

    session = StreamSession(BlockingFacade(), admission, "req-send", None, "hello", {})
    session.start()
    assert entered.wait(timeout=1)
    response = BoundedSSEStreamingResponse(session, send_wait_seconds=0.01)

    async def blocked_asgi_send():
        async def receive():
            await asyncio.Future()

        async def send(message):
            await asyncio.Future()

        scope = {"type": "http", "method": "POST", "path": "/chat/stream", "headers": []}
        await response(scope, receive, send)

    started_at = time.monotonic()
    asyncio.run(blocked_asgi_send())
    assert time.monotonic() - started_at < 0.5
    assert session._reason() == "slow_consumer"
    assert admission.locked()
    assert not closed.is_set()
    release.set()
    assert session._finished.wait(timeout=1)
    assert closed.is_set()
    assert not admission.locked()


def test_http_disconnect_stops_asgi_delivery_and_retains_slot_until_worker_closes():
    admission = Lock()
    admission.acquire()
    entered, release, closed = Event(), Event(), Event()
    received_body = Event()

    class BlockingFacade:
        def stream(self, **kwargs):
            try:
                yield ChatChunk(content="first")
                entered.set()
                release.wait(timeout=2)
                yield ChatChunk(content="discarded")
            finally:
                closed.set()

    session = StreamSession(BlockingFacade(), admission, "req-disconnect", None, "hello", {})
    session.start()
    response = BoundedSSEStreamingResponse(session, send_wait_seconds=0.2)

    async def exercise_disconnect():
        async def receive():
            await asyncio.to_thread(received_body.wait, 1)
            await asyncio.to_thread(entered.wait, 1)
            return {"type": "http.disconnect"}

        async def send(message):
            if message.get("type") == "http.response.body" and message.get("body"):
                received_body.set()

        scope = {"type": "http", "method": "POST", "path": "/chat/stream", "headers": []}
        await response(scope, receive, send)
        return [task for task in asyncio.all_tasks() if task is not asyncio.current_task() and not task.done()]

    assert asyncio.run(exercise_disconnect()) == []
    assert session._reason() == "disconnect"
    assert admission.locked()
    assert not closed.is_set()
    release.set()
    assert session._finished.wait(timeout=1)
    assert closed.is_set()
    assert not admission.locked()


def test_asgi_request_cancellation_cleans_up_owned_response_tasks():
    admission = Lock()
    admission.acquire()
    entered, release, closed = Event(), Event(), Event()

    class BlockingFacade:
        def stream(self, **kwargs):
            try:
                entered.set()
                release.wait(timeout=2)
                yield ChatChunk(content="late")
            finally:
                closed.set()

    session = StreamSession(BlockingFacade(), admission, "req-cancel", None, "hello", {})
    session.start()
    response = BoundedSSEStreamingResponse(session, send_wait_seconds=1)

    async def cancel_request():
        asgi_started = asyncio.Event()

        async def receive():
            await asyncio.Future()

        async def send(message):
            if message["type"] == "http.response.start":
                asgi_started.set()

        scope = {"type": "http", "method": "POST", "path": "/chat/stream", "headers": []}
        request_task = asyncio.create_task(response(scope, receive, send))
        # A ready worker alone does not prove the response task has run.
        await asyncio.wait_for(asgi_started.wait(), timeout=1)
        assert await asyncio.to_thread(entered.wait, 1)
        request_task.cancel()
        with suppress(asyncio.CancelledError):
            await request_task
        return [task for task in asyncio.all_tasks() if task is not asyncio.current_task() and not task.done()]

    assert asyncio.run(cancel_request()) == []
    assert session._reason() == "disconnect"
    assert admission.locked()
    assert not closed.is_set()
    release.set()
    assert session._finished.wait(timeout=1)
    assert closed.is_set()
    assert not admission.locked()


def test_stream_frames_split_at_unicode_boundaries_and_remain_bounded():
    from oratrice_api.streaming import _text_frames

    text = ("\x00\U0001f343\n" * 7000)
    assert "".join(_text_frames(text)) == text
    assert len(_text_frames(text)) > 1
    assert all(len(_json_sse("delta", {"text": item})) <= 16 * 1024 for item in _text_frames(text))
