"""Strict HTTP DTOs and safe serializers for the Oratrice API.

The API layer deliberately exposes only provider-neutral contracts.  Raw
transport responses, exception causes, and user prompt fields are filtered at
this boundary before a response is returned to a client.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, TypeAlias

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr


Message: TypeAlias = str | list[Any]


class _StrictDTO(BaseModel):
    """Base request DTO: unknown fields are rejected instead of ignored."""

    model_config = ConfigDict(extra="forbid")


class RouteRequest(_StrictDTO):
    message: Message
    model: StrictStr | None = None
    provider: StrictStr | None = None
    capabilities: list[StrictStr] | None = None
    requires_vision: StrictBool = False
    requires_network: StrictBool = False
    requires_tools: StrictBool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(RouteRequest):
    temperature: StrictFloat | None = None
    max_tokens: StrictInt | None = None
    top_p: StrictFloat | None = None
    stop: StrictStr | list[StrictStr] | None = None


# Descriptive aliases for callers that prefer an explicit DTO suffix.
RouteRequestDTO = RouteRequest
ChatRequestDTO = ChatRequest


_CHAT_KEYS = frozenset(
    {"content", "model", "finish_reason", "usage", "provider", "request_id", "metadata"}
)
_ROUTE_KEYS = frozenset(
    {
        "model",
        "provider",
        "task_type",
        "complexity",
        "capabilities",
        "requires_vision",
        "requires_network",
        "requires_tools",
        "reason",
        "confidence",
    }
)
_HEALTH_KEYS = frozenset(
    {"status", "healthy", "components", "checked_at", "request_id", "details"}
)
_DROP_KEYS = frozenset({"raw", "cause", "prompt", "messages", "input", "body"})


def _safe_value(value: Any) -> Any:
    """Recursively remove transport/debug/prompt fields from response data."""

    if isinstance(value, Mapping):
        return {
            str(key): _safe_value(child)
            for key, child in value.items()
            if str(key).lower() not in _DROP_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_safe_value(child) for child in value]
    return value


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        result = to_dict()
        if isinstance(result, Mapping):
            return dict(result)
    values = getattr(value, "__dict__", None)
    return dict(values) if isinstance(values, Mapping) else {}


def _serialise(value: Any, keys: frozenset[str]) -> dict[str, Any]:
    source = _mapping(value)
    result = {key: _safe_value(source[key]) for key in keys if key in source}
    # Pydantic/FastAPI's encoder handles datetimes and other benign values in
    # health/provider metadata without exposing the original object.
    encoded = jsonable_encoder(result)
    return encoded if isinstance(encoded, dict) else {}


def serialise_chat_response(value: Any) -> dict[str, Any]:
    """Return a safe ChatResponse-compatible JSON mapping."""

    result = _serialise(value, _CHAT_KEYS)
    result.setdefault("content", "")
    return result


def serialise_route_decision(value: Any, *, request_id: str) -> dict[str, Any]:
    """Return only RouteDecision fields plus the API correlation ID."""

    result = _serialise(value, _ROUTE_KEYS)
    result["request_id"] = request_id
    return result


def serialise_health(value: Any, *, request_id: str | None = None) -> dict[str, Any]:
    """Return the stable HealthReport envelope without raw diagnostics."""

    result = _serialise(value, _HEALTH_KEYS)
    if request_id is not None:
        result.setdefault("request_id", request_id)
    result.setdefault("status", "unknown")
    result.setdefault("healthy", False)
    result.setdefault("components", {})
    return result


def health_envelope(
    *,
    status: str,
    healthy: bool,
    components: Any = None,
    request_id: str | None = None,
    checked_at: datetime | str | None = None,
    details: Any = None,
) -> dict[str, Any]:
    """Build a safe health-compatible response for liveness/readiness probes.

    ``serialise_health`` remains the compatibility adapter for a facade
    ``HealthReport``.  This helper is for probe responses that do not have a
    report object (notably ``/live``) or that need to override the aggregate
    status after classifying required and optional dependencies (``/ready``).
    It deliberately uses the same allow-list and recursive redaction as the
    existing health serializer.
    """

    source: dict[str, Any] = {
        "status": status,
        "healthy": bool(healthy),
        "components": components if components is not None else {},
    }
    if request_id is not None:
        source["request_id"] = request_id
    if checked_at is not None:
        source["checked_at"] = checked_at
    if details is not None:
        source["details"] = details
    return _serialise(source, _HEALTH_KEYS)


# American-spelling aliases match common API naming conventions.
serialize_chat_response = serialise_chat_response
serialize_route_decision = serialise_route_decision
serialize_health = serialise_health


__all__ = [
    "ChatRequest",
    "ChatRequestDTO",
    "RouteRequest",
    "RouteRequestDTO",
    "serialise_chat_response",
    "health_envelope",
    "serialise_health",
    "serialise_route_decision",
    "serialize_chat_response",
    "serialize_health",
    "serialize_route_decision",
]
