"""Small, dependency-free observability primitives used by Oratrice.

The application deliberately keeps observability at the core boundary.  This
module provides three things that are useful to every layer without importing
an HTTP/logging SDK:

* a request/correlation-id context;
* structured logging with conservative redaction; and
* a mapping-like health report for the facade and its dependencies.

The logger never serialises prompts, message content, credentials, or
``Authorization`` headers.  Callers should pass event metadata rather than
raw request payloads; the redactor is a second safety net for test doubles and
integration code that accidentally supplies a sensitive key.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import re
import uuid
from collections.abc import Iterator, Mapping
from typing import Any, Callable


_REQUEST_ID: ContextVar[str | None] = ContextVar("oratrice_request_id", default=None)


def new_request_id(factory: Callable[[], str] | None = None) -> str:
    """Return a non-empty request id.

    ``factory`` exists solely to make correlation deterministic in offline
    tests.  A malformed factory result is rejected rather than silently
    emitting an uncorrelatable log record.
    """

    value = factory() if factory is not None else uuid.uuid4().hex
    if not isinstance(value, str) or not value.strip():
        raise ValueError("request id factory must return a non-empty string")
    return value.strip()


def get_request_id(default: str | None = None) -> str | None:
    """Read the id associated with the current execution context."""

    return _REQUEST_ID.get() or default


def set_request_id(request_id: str | None) -> Any:
    """Set the current id and return a context token for ``reset_request_id``."""

    if request_id is not None:
        request_id = str(request_id).strip()
        if not request_id:
            raise ValueError("request id must be a non-empty string")
    return _REQUEST_ID.set(request_id)


def reset_request_id(token: Any) -> None:
    """Restore a context returned by :func:`set_request_id`."""

    _REQUEST_ID.reset(token)


@contextmanager
def request_context(request_id: str | None = None, *, factory: Callable[[], str] | None = None) -> Iterator[str]:
    """Temporarily bind a correlation id and yield it.

    An explicit id is preserved; otherwise an id is generated.  ContextVars
    make this safe for concurrent async requests and regular threads.
    """

    value = str(request_id).strip() if request_id is not None else new_request_id(factory)
    if not value:
        raise ValueError("request id must be a non-empty string")
    token = _REQUEST_ID.set(value)
    try:
        yield value
    finally:
        _REQUEST_ID.reset(token)


# Common secret/payload names.  Matching is intentionally broad: it is safer
# to replace a harmless metadata value than to put a bearer token into logs.
_SENSITIVE_KEY = re.compile(
    r"(?:^|[_\-.])(api[_.-]?key|access[_.-]?token|auth(?:orization)?|bearer|credential|password|passwd|secret|token|private[_.-]?key|prompt|messages?|content|input|output|body|payload|headers?)(?:$|[_\-.])",
    re.IGNORECASE,
)
_AUTH_VALUE = re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+")
_KEY_VALUE = re.compile(
    r"(?i)(?P<label>api[_\-.]?key|access[_\-.]?token|authorization|secret|password|token)\s*[:=]\s*([^\s,;]+)"
)


def _sensitive_key(key: Any) -> bool:
    text = str(key)
    return bool(_SENSITIVE_KEY.search(text))


def redact(value: Any, *, key: Any | None = None, replacement: str = "[REDACTED]") -> Any:
    """Return a JSON-friendly, recursively redacted value.

    No object is mutated.  Exception and arbitrary SDK objects are converted
    to a type name instead of calling their potentially secret-bearing
    ``repr``/``str`` implementation.
    """

    if key is not None and _sensitive_key(key):
        return replacement
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        # Never emit a bearer/basic token even when supplied as a free-form
        # event value.  Do not redact ordinary text, including error labels.
        return _AUTH_VALUE.sub("[REDACTED]", value)
    if isinstance(value, Mapping):
        return {str(child_key): redact(child, key=child_key, replacement=replacement) for child_key, child in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact(child, replacement=replacement) for child in value]
    if isinstance(value, BaseException):
        return {"type": type(value).__name__}
    return {"type": type(value).__name__}


def redact_text(value: Any) -> str:
    """Safely render a diagnostic text without credentials or prompt fields."""

    if isinstance(value, BaseException):
        return type(value).__name__
    text = str(value)
    text = _AUTH_VALUE.sub("[REDACTED]", text)
    return _KEY_VALUE.sub(lambda match: f"{match.group('label')}=[REDACTED]", text)


class StructuredLogger:
    """Adapter around :mod:`logging` that emits one JSON object per record.

    ``sink`` is an optional callable receiving the already-redacted mapping;
    it is useful for deterministic tests and embedding in an application that
    has its own event collector.  The standard logger remains the default and
    no output is written directly to stdout/stderr by this class.
    """

    def __init__(self, logger: logging.Logger | str | None = None, *, sink: Callable[[Mapping[str, Any]], Any] | None = None):
        if logger is None:
            logger = logging.getLogger("oratrice")
        elif isinstance(logger, str):
            logger = logging.getLogger(logger)
        self.logger = logger
        self.sink = sink

    def event(self, event: str, *, level: int = logging.INFO, request_id: str | None = None, **fields: Any) -> dict[str, Any]:
        """Emit a redacted structured event and return its payload."""

        payload: dict[str, Any] = {
            "event": str(event),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        correlation = request_id or get_request_id()
        if correlation:
            payload["request_id"] = correlation
        for key, value in fields.items():
            # Preserve explicit None only when callers ask for it; omitting
            # optional fields makes records stable and easier to aggregate.
            if value is None:
                continue
            payload[str(key)] = value
        safe = redact(payload)
        if self.sink is not None:
            self.sink(safe)
        # JSON encoding is deterministic and keeps log messages structured for
        # plain handlers.  ``extra`` gives structured handlers the original
        # mapping without exposing the unredacted fields.
        try:
            rendered = json.dumps(safe, ensure_ascii=False, sort_keys=True, default=str)
        except Exception:
            rendered = json.dumps({"event": str(event), "request_id": correlation}, sort_keys=True)
        self.logger.log(level, rendered, extra={"oratrice_event": safe})
        return safe

    def debug(self, event: str, **fields: Any) -> dict[str, Any]:
        return self.event(event, level=logging.DEBUG, **fields)

    def info(self, event: str, **fields: Any) -> dict[str, Any]:
        return self.event(event, level=logging.INFO, **fields)

    def warning(self, event: str, **fields: Any) -> dict[str, Any]:
        return self.event(event, level=logging.WARNING, **fields)

    warn = warning

    def error(self, event: str, **fields: Any) -> dict[str, Any]:
        return self.event(event, level=logging.ERROR, **fields)

    def exception(self, event: str, *, exc: BaseException | None = None, **fields: Any) -> dict[str, Any]:
        if exc is not None:
            fields.setdefault("error_type", type(exc).__name__)
            code = getattr(exc, "code", None)
            if code:
                fields.setdefault("error_code", code)
        # Deliberately do not pass ``exc_info``: traceback formatting can
        # include request payloads or credentials supplied by an SDK.
        return self.event(event, level=logging.ERROR, **fields)


def get_logger(name: str = "oratrice", *, sink: Callable[[Mapping[str, Any]], Any] | None = None) -> StructuredLogger:
    """Return an injectable structured logger for ``name``."""

    return StructuredLogger(name, sink=sink)


@dataclass(frozen=True)
class HealthReport(Mapping[str, Any]):
    """Aggregate health result returned by :class:`core.ai_service.CoreFacade`."""

    status: str = "unknown"
    components: Mapping[str, Any] = field(default_factory=dict)
    request_id: str | None = None
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    details: Mapping[str, Any] = field(default_factory=dict)

    @property
    def healthy(self) -> bool:
        return self.status.lower() in {"ok", "healthy", "ready", "up"}

    @property
    def ok(self) -> bool:
        return self.healthy

    @property
    def is_healthy(self) -> bool:
        return self.healthy

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status,
            "healthy": self.healthy,
            "components": dict(self.components),
            "checked_at": self.checked_at.isoformat(),
        }
        # Convenience access for health endpoints that historically exposed
        # ``providers``/``runtimes`` as top-level keys.
        for key in ("providers", "runtimes", "router", "runtime"):
            if key in self.components:
                result[key] = self.components[key]
        if self.request_id is not None:
            result["request_id"] = self.request_id
        if self.details:
            result["details"] = dict(self.details)
        return result

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __iter__(self):
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())


# Friendly aliases used by integrations that call this an audit/event logger.
JsonLogger = StructuredLogger
CorrelationLogger = StructuredLogger
StructuredLog = StructuredLogger
correlation_id = get_request_id
get_correlation_id = get_request_id
with_request_id = request_context
request_id_context = request_context
new_correlation_id = new_request_id
sanitize = redact
redact_sensitive = redact
redact_data = redact
sanitize_payload = redact


__all__ = [
    "CorrelationLogger",
    "HealthReport",
    "JsonLogger",
    "StructuredLogger",
    "StructuredLog",
    "correlation_id",
    "get_correlation_id",
    "get_logger",
    "get_request_id",
    "new_request_id",
    "new_correlation_id",
    "redact",
    "redact_sensitive",
    "redact_text",
    "request_context",
    "request_id_context",
    "reset_request_id",
    "sanitize",
    "sanitize_payload",
    "redact_data",
    "set_request_id",
    "with_request_id",
]
