"""Bounded SSE delivery for synchronous facade streams.

One worker owns facade setup, iteration, and iterator cleanup.  Disconnecting
the HTTP client stops delivery only; the worker drains and discards output
until its provider iterator ends, then releases the shared API admission slot.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
import json
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
import time
from typing import Any

from core.errors import (
    CoreConfigurationError,
    CoreError,
    CoreProviderError,
    CoreRoutingError,
    CoreRuntimeError,
    CoreValidationError,
)
from fastapi.responses import Response


MAX_QUEUED_EVENTS = 8
MAX_FRAME_BYTES = 16 * 1024
MAX_TEXT_BYTES = 64 * 1024
MAX_PROVIDER_EVENTS = 4096
QUEUE_WAIT_SECONDS = 5.0
SEND_WAIT_SECONDS = 5.0
STREAM_DELIVERY_SECONDS = 120.0
_QUEUE_POLL_SECONDS = 0.01
_PRODUCER_POLL_SECONDS = 0.05
_MAX_DELTA_EVENTS = MAX_PROVIDER_EVENTS - 2


@dataclass(frozen=True, slots=True)
class _SafeFailure:
    code: str
    message: str


def _safe_failure(error: BaseException) -> _SafeFailure:
    """Map errors to fixed public text; never serialize provider details."""

    code = error.code if isinstance(error, CoreError) else None
    if code == "stream_unsupported":
        return _SafeFailure("stream_unsupported", "The selected model provider does not support streaming.")
    if isinstance(error, CoreRoutingError):
        return _SafeFailure("routing_error", "Oratrice could not select a route for this request.")
    if isinstance(error, CoreProviderError):
        return _SafeFailure("upstream_error", "The model service failed to stream this response.")
    if isinstance(error, (CoreConfigurationError, CoreRuntimeError)):
        return _SafeFailure("service_unavailable", "The configured model service is unavailable.")
    if isinstance(error, CoreValidationError):
        return _SafeFailure("stream_error", "Oratrice could not start this response.")
    return _SafeFailure("stream_error", "Oratrice could not complete this response.")


def _json_sse(event: str, payload: Mapping[str, Any]) -> bytes:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return ("event: " + event + "\ndata: " + body + "\n\n").encode("utf-8")


def _text_frames(text: str) -> list[str]:
    """Split text on code-point boundaries so JSON frames stay under 16 KiB."""

    # Six ASCII bytes per code point bounds JSON's largest escaped control
    # character.  Include small event/JSON framing headroom in the slice.
    max_codepoints = (MAX_FRAME_BYTES - 128) // 6
    return [text[index:index + max_codepoints] for index in range(0, len(text), max_codepoints)]


class StreamSession:
    """Own one facade stream on a worker and deliver bounded public events."""

    def __init__(
        self,
        facade: Any,
        admission: Any,
        request_id: str,
        model: str | None,
        message: str,
        values: Mapping[str, Any],
        *,
        max_queued_events: int = MAX_QUEUED_EVENTS,
        max_text_bytes: int = MAX_TEXT_BYTES,
        max_provider_events: int = MAX_PROVIDER_EVENTS,
        queue_wait_seconds: float = QUEUE_WAIT_SECONDS,
        delivery_seconds: float = STREAM_DELIVERY_SECONDS,
        queue_poll_seconds: float = _QUEUE_POLL_SECONDS,
        producer_poll_seconds: float = _PRODUCER_POLL_SECONDS,
        status_token: int | None = None,
    ) -> None:
        self.facade = facade
        self.admission = admission
        self.request_id = request_id
        self.model = model
        self.message = message
        self.values = dict(values)
        self._status_token = status_token
        self._queue: Queue[dict[str, Any]] = Queue(maxsize=max_queued_events)
        self._max_text_bytes = max_text_bytes
        self._max_provider_events = max_provider_events
        self._queue_wait_seconds = queue_wait_seconds
        self._delivery_seconds = delivery_seconds
        self._queue_poll_seconds = queue_poll_seconds
        self._producer_poll_seconds = producer_poll_seconds
        self._cancel_delivery = Event()
        self._finished = Event()
        self._started_at = time.monotonic()
        self._reason_lock = Lock()
        self._stop_reason: str | None = None
        self._thread = Thread(target=self._produce, name="oratrice-chat-stream", daemon=True)

    @property
    def finished(self) -> bool:
        return self._finished.is_set()

    def start(self) -> None:
        """Start owned work. The caller keeps the admission slot on success."""

        self._thread.start()

    def stop_delivery(self, reason: str) -> None:
        """Stop publishing events while leaving iterator ownership to worker."""

        changed = False
        with self._reason_lock:
            if self._stop_reason is None:
                self._stop_reason = reason
                self._cancel_delivery.set()
                changed = True
        if changed:
            notify = getattr(self.admission, "mark_delivery_stopped", None)
            if callable(notify):
                try:
                    if self._status_token is None:
                        notify()
                    else:
                        notify(self._status_token)
                except Exception:
                    # Optional status instrumentation must not interrupt the
                    # stream's delivery-stop and worker-drain contract.
                    pass

    def _mark_operation_failed(self) -> None:
        """Notify the API status tracker without requiring a custom lock type."""

        notify = getattr(self.admission, "mark_failed", None)
        if callable(notify):
            try:
                if self._status_token is None:
                    notify()
                else:
                    notify(self._status_token)
            except Exception:
                # Keep worker cleanup authoritative even if instrumentation
                # supplied by an embedding API is faulty.
                pass

    def _reason(self) -> str | None:
        with self._reason_lock:
            return self._stop_reason

    def _put(self, event: dict[str, Any]) -> bool:
        deadline = time.monotonic() + self._queue_wait_seconds
        while not self._cancel_delivery.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.stop_delivery("slow_consumer")
                return False
            try:
                self._queue.put(event, timeout=min(self._producer_poll_seconds, remaining))
                return True
            except Full:
                continue
        return False

    def _produce(self) -> None:
        stream: Any = None
        iterator: Any = None
        terminal: dict[str, Any] | None = None
        try:
            # Calling facade.stream can route, start a runtime, and return a
            # provider iterator, so it belongs on this same worker as next().
            stream = self.facade.stream(model_id=self.model, message=self.message, **self.values)
            iterator = iter(stream)
            total_bytes = 0
            provider_events = 0
            delta_events = 0
            finish_reason: str | None = None
            while True:
                try:
                    chunk = next(iterator)
                except StopIteration:
                    break
                provider_events += 1
                if provider_events > self._max_provider_events:
                    self.stop_delivery("stream_limit")
                text = chunk if isinstance(chunk, str) else getattr(chunk, "content", None)
                if not isinstance(text, str):
                    raise TypeError("stream chunk did not contain text")
                reason = getattr(chunk, "finish_reason", None)
                if isinstance(reason, str) and len(reason) <= 64:
                    finish_reason = reason
                if self._cancel_delivery.is_set():
                    continue
                text_bytes = len(text.encode("utf-8"))
                if total_bytes + text_bytes > self._max_text_bytes:
                    self.stop_delivery("stream_limit")
                    continue
                total_bytes += text_bytes
                for fragment in _text_frames(text):
                    if delta_events >= _MAX_DELTA_EVENTS:
                        self.stop_delivery("stream_limit")
                        break
                    if not self._put({"event": "delta", "data": {"text": fragment}}):
                        break
                    delta_events += 1

            if not self._cancel_delivery.is_set():
                terminal = {"event": "complete", "data": {"finish_reason": finish_reason}}
        except Exception as error:
            self._mark_operation_failed()
            terminal = {"event": "error", "data": {
                "error": {"code": "stream_error", "message": "Oratrice could not complete this response.", "request_id": self.request_id},
                "work_may_continue": True,
            }}
            safe = _safe_failure(error)
            terminal["data"]["error"]["code"] = safe.code
            terminal["data"]["error"]["message"] = safe.message
        finally:
            try:
                close = getattr(iterator, "close", None)
                if not callable(close):
                    close = getattr(stream, "close", None)
                if callable(close):
                    close()
            except Exception:
                self._mark_operation_failed()
                terminal = {"event": "error", "data": {
                    "error": {"code": "stream_error", "message": "Oratrice could not complete this response.", "request_id": self.request_id},
                    "work_may_continue": True,
                }}
            finally:
                if terminal is not None and not self._cancel_delivery.is_set():
                    self._put(terminal)
                self.admission.release()
                self._finished.set()

    async def events(self) -> AsyncIterator[bytes]:
        """Yield SSE body bytes until a terminal event or delivery stop."""

        yield _json_sse("start", {
            "version": 1,
            "request_id": self.request_id,
            "cancellation": "stop_wait_only",
        })
        deadline = self._started_at + self._delivery_seconds
        while True:
            reason = self._reason()
            if reason is not None:
                yield _json_sse("cancelled", {"reason": reason, "work_may_continue": True})
                return
            if time.monotonic() >= deadline:
                self.stop_delivery("timeout")
                yield _json_sse("cancelled", {"reason": "timeout", "work_may_continue": True})
                return
            try:
                event = self._queue.get_nowait()
            except Empty:
                if self._finished.is_set():
                    return
                await asyncio.sleep(self._queue_poll_seconds)
                continue
            yield _json_sse(event["event"], event["data"])
            if event["event"] in {"complete", "error"}:
                return


class BoundedSSEStreamingResponse(Response):
    """SSE response with a bounded wait for each ASGI body send."""

    def __init__(self, session: StreamSession, *, send_wait_seconds: float = SEND_WAIT_SECONDS) -> None:
        self.session = session
        self.send_wait_seconds = send_wait_seconds
        super().__init__(
            content=b"",
            status_code=200,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )
        # Response's regular body is empty because this class streams its own
        # ASGI messages; advertising Content-Length: 0 would truncate the SSE.
        self.raw_headers = [
            (key, value)
            for key, value in self.raw_headers
            if key.lower() != b"content-length"
        ]

    async def __call__(self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]) -> None:
        async def send_stream() -> None:
            try:
                await asyncio.wait_for(send({
                    "type": "http.response.start",
                    "status": self.status_code,
                    "headers": self.raw_headers,
                }), timeout=self.send_wait_seconds)
            except TimeoutError:
                self.session.stop_delivery("slow_consumer")
                return

            events = self.session.events()
            try:
                while True:
                    try:
                        frame = await events.__anext__()
                    except StopAsyncIteration:
                        break
                    try:
                        await asyncio.wait_for(send({
                            "type": "http.response.body",
                            "body": frame,
                            "more_body": True,
                        }), timeout=self.send_wait_seconds)
                    except TimeoutError:
                        # The blocked frame may have been discarded. Offer one
                        # bounded terminal event, then end this HTTP delivery.
                        self.session.stop_delivery("slow_consumer")
                        try:
                            cancelled = await asyncio.wait_for(events.__anext__(), timeout=0.05)
                            await asyncio.wait_for(send({
                                "type": "http.response.body",
                                "body": cancelled,
                                "more_body": False,
                            }), timeout=0.1)
                        except (StopAsyncIteration, TimeoutError, OSError, RuntimeError):
                            pass
                        return
                try:
                    await asyncio.wait_for(send({
                        "type": "http.response.body",
                        "body": b"",
                        "more_body": False,
                    }), timeout=self.send_wait_seconds)
                except TimeoutError:
                    self.session.stop_delivery("slow_consumer")
            finally:
                await events.aclose()

        async def wait_for_disconnect() -> None:
            while True:
                message = await receive()
                if message.get("type") == "http.disconnect":
                    return

        send_task = asyncio.create_task(send_stream())
        disconnect_task = asyncio.create_task(wait_for_disconnect())
        try:
            done, _ = await asyncio.wait(
                {send_task, disconnect_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if disconnect_task in done:
                self.session.stop_delivery("disconnect")
                send_task.cancel()
                await asyncio.gather(send_task, return_exceptions=True)
            else:
                # Surface transport errors to the ASGI server. Client closes
                # and bounded-send timeouts are handled by the request tasks.
                await send_task
        except OSError:
            self.session.stop_delivery("disconnect")
        finally:
            if not self.session.finished:
                self.session.stop_delivery("disconnect")
            send_task.cancel()
            disconnect_task.cancel()
            await asyncio.gather(send_task, disconnect_task, return_exceptions=True)


__all__ = [
    "BoundedSSEStreamingResponse",
    "MAX_FRAME_BYTES",
    "MAX_PROVIDER_EVENTS",
    "MAX_QUEUED_EVENTS",
    "MAX_TEXT_BYTES",
    "QUEUE_WAIT_SECONDS",
    "SEND_WAIT_SECONDS",
    "STREAM_DELIVERY_SECONDS",
    "StreamSession",
]
