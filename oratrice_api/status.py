"""Private, bounded status state for one Core API application instance.

This module tracks only whether an API-owned operation is in progress and a
cached result from an explicitly supplied readiness source. It deliberately
does not ask the Core facade to perform health checks or model work.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
import time
from typing import Callable, Literal


StatusOperation = Literal["chat", "route", "stream"]
ReadinessState = Literal["ready", "starting", "error", "unavailable"]


@dataclass(frozen=True, slots=True)
class OperationSnapshot:
    busy: bool
    operation: StatusOperation | None
    delivery: Literal["active", "stopped"] | None
    operation_failed: bool


class OperationStatusTracker:
    """A non-queueing admission slot with an atomic, safe status snapshot.

    ``acquire`` follows the ``threading.Lock`` shape used by the API. The
    underlying lock stays held until the owning sync request or stream worker
    releases it, so a stopped HTTP stream remains busy while its provider
    iterator is still draining and closing.

    A retained operation failure is cleared when the next operation is
    admitted. If that operation fails, it records a new failure on release.
    """

    def __init__(self) -> None:
        self._gate = Lock()
        self._metadata_lock = Lock()
        self._busy = False
        self._operation: StatusOperation | None = None
        self._delivery: Literal["active", "stopped"] | None = None
        self._operation_failed = False
        self._generation = 0

    def acquire(
        self,
        blocking: bool = True,
        timeout: float = -1,
        *,
        operation: StatusOperation | None = None,
    ) -> bool:
        """Acquire the one API operation slot without queueing by default."""

        acquired = (
            self._gate.acquire(blocking)
            if timeout == -1
            else self._gate.acquire(blocking, timeout)
        )
        if not acquired:
            return False
        with self._metadata_lock:
            self._generation += 1
            self._busy = True
            self._operation = operation
            self._delivery = "active" if operation == "stream" else None
            # The failure policy is "clear on begin" so a hung retry is shown
            # as busy and a failed retry records its own failure.
            self._operation_failed = False
        return True

    def release(self) -> None:
        """Release the slot after the operation and any stream cleanup finish."""

        with self._metadata_lock:
            if not self._busy:
                raise RuntimeError("API operation slot was already released")
            # Release the gate while metadata is protected. A status reader
            # cannot observe an idle snapshot while a new owner already holds
            # the gate.
            self._gate.release()
            self._busy = False
            self._operation = None
            self._delivery = None

    def locked(self) -> bool:
        """Match ``threading.Lock.locked`` for narrow compatibility."""

        return self._gate.locked()

    def current_token(self) -> int | None:
        """Return the generation token of the current admitted operation."""

        with self._metadata_lock:
            return self._generation if self._busy else None

    def mark_failed(self, token: int | None = None) -> None:
        """Remember a safe operation-failure code until the next admission."""

        with self._metadata_lock:
            if not self._busy or (token is not None and token != self._generation):
                return
            self._operation_failed = True

    def mark_delivery_stopped(self, token: int | None = None) -> None:
        """Record that stream delivery stopped while provider work may remain."""

        with self._metadata_lock:
            if (
                self._busy
                and self._operation == "stream"
                and (token is None or token == self._generation)
            ):
                self._delivery = "stopped"

    def snapshot(self) -> OperationSnapshot:
        """Read busy state and all operation metadata under one lock."""

        with self._metadata_lock:
            return OperationSnapshot(
                busy=self._busy,
                operation=self._operation if self._busy else None,
                delivery=self._delivery if self._busy else None,
                operation_failed=self._operation_failed,
            )


class ReadinessCache:
    """Single-flight cache for explicit, read-only readiness probes."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 5.0,
        max_stale_seconds: float = 15.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._ttl_seconds = max(0.0, ttl_seconds)
        self._max_stale_seconds = max(self._ttl_seconds, max_stale_seconds)
        self._clock = clock or time.monotonic
        self._lock = Lock()
        self._probing = False
        self._cached_key: tuple[object, ...] | None = None
        self._cached_provider: object | None = None
        self._cached_at: float | None = None
        self._cached_ready: bool | None = None
        self._cached_failed = False
        self._ever_ready = False

    def sample(
        self,
        provider: object | None,
        probe: Callable[[], bool] | None = None,
    ) -> ReadinessState:
        """Return a safe readiness classification, invoking at most one probe.

        A missing explicit provider never triggers facade health or provider
        construction. If a source disappears after previously reporting ready,
        the loss is reported as a readiness failure.
        """

        now = self._clock()
        key = _provider_key(provider) if provider is not None else None
        with self._lock:
            if provider is None or probe is None:
                return "error" if self._ever_ready else "unavailable"

            same_source = self._cached_key == key and self._cached_at is not None
            if same_source and now - self._cached_at < self._ttl_seconds:
                return self._classification_locked()
            if self._probing:
                if same_source:
                    age = now - self._cached_at
                    if age <= self._max_stale_seconds:
                        # Keep serving a bounded-stale result while a refresh
                        # is in flight; never start a second checker call.
                        return self._classification_locked()
                    # A hung checker must not let an old ready result survive
                    # indefinitely while other polls return immediately.
                    return "error"
                return "starting"
            self._probing = True

        ready = False
        failed = False
        try:
            ready = bool(probe())
        except Exception:
            # Status is an operator hint; checker exception details are never
            # copied into the public response.
            failed = True
        finally:
            with self._lock:
                self._cached_key = key
                # Retain one bounded source reference so bound-method owners
                # cannot be collected and have their object ID reused.
                self._cached_provider = provider
                self._cached_at = self._clock()
                self._cached_ready = ready if not failed else None
                self._cached_failed = failed
                if ready and not failed:
                    self._ever_ready = True
                self._probing = False
        with self._lock:
            return self._classification_locked()

    def _classification_locked(self) -> ReadinessState:
        if self._cached_failed:
            return "error"
        if self._cached_ready is True:
            return "ready"
        if self._cached_ready is False and self._ever_ready:
            return "error"
        if self._cached_ready is False:
            return "starting"
        return "starting"


def _provider_key(provider: object) -> tuple[object, ...]:
    """Give repeated bound-method lookups one stable source identity."""

    try:
        owner = getattr(provider, "__self__", None)
        function = getattr(provider, "__func__", None)
    except Exception:
        return ("object", id(provider))
    if owner is not None and function is not None:
        return ("method", id(owner), id(function))
    return ("object", id(provider))


def status_payload(
    operation: OperationSnapshot,
    readiness: ReadinessState | None,
) -> dict[str, object]:
    """Build the versioned public status shape from safe internal enums."""

    error_code: str | None = None
    if operation.busy:
        state = "busy"
    elif operation.operation_failed:
        state = "error"
        error_code = "operation_failed"
    elif readiness == "ready":
        state = "ready"
    elif readiness == "error":
        state = "error"
        error_code = "readiness_failed"
    elif readiness == "unavailable":
        state = "starting"
        error_code = "readiness_unavailable"
    else:
        state = "starting"

    return {
        "version": 1,
        "state": state,
        "operation": operation.operation if operation.busy else None,
        "delivery": operation.delivery if operation.busy else None,
        "error_code": error_code,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


__all__ = [
    "OperationSnapshot",
    "OperationStatusTracker",
    "ReadinessCache",
    "ReadinessState",
    "status_payload",
]
