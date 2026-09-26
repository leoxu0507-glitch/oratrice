"""HTTP error mapping for the provider-neutral Oratrice API."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.errors import (
    CoreConfigurationError,
    CoreError,
    CoreHealthError,
    CoreProviderError,
    CoreRoutingError,
    CoreRuntimeError,
    CoreValidationError,
)
from core.observability import redact, redact_text
from router.contracts import RouterTransportError


def status_for_error(exc: BaseException) -> int:
    """Map stable core error classes to API status codes."""

    if isinstance(exc, CoreValidationError):
        return 422
    if isinstance(exc, CoreRoutingError):
        # A routing decision that could not be obtained because the injected
        # router transport failed is an upstream dependency failure.  Keep
        # ordinary policy/validation failures as client-facing 422 responses.
        if isinstance(getattr(exc, "cause", None), RouterTransportError):
            return 503
        return 422
    if isinstance(exc, CoreProviderError):
        return 502
    if isinstance(exc, (CoreRuntimeError, CoreConfigurationError, CoreHealthError)):
        return 503
    if isinstance(exc, CoreError):
        return 500
    return 500


def _safe_details(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _safe_details(child)
            for key, child in value.items()
            if str(key).lower() not in {"raw", "cause", "prompt", "input", "body", "messages"}
        }
    if isinstance(value, (list, tuple)):
        return [_safe_details(child) for child in value]
    if isinstance(value, str):
        return _safe_message(value)
    return value


def _safe_message(value: str) -> str:
    """Keep ordinary diagnostics while suppressing prompt-like text."""

    lowered = value.lower()
    sensitive_markers = (
        "prompt",
        "message=",
        "input=",
        "body=",
        "api_key",
        "authorization",
        "bearer ",
        "secret",
    )
    if any(marker in lowered for marker in sensitive_markers):
        return "request failed"
    return redact_text(value)


def error_payload(exc: BaseException, *, request_id: str | None = None) -> dict[str, Any]:
    """Return an exception envelope without causes, stacks, or user input."""

    if isinstance(exc, CoreError):
        result = dict(exc.to_dict())
        result.pop("cause", None)
        result["message"] = _safe_message(str(result.get("message", "request failed")))
        if request_id is not None:
            result.setdefault("request_id", request_id)
        if "details" in result:
            result["details"] = _safe_details(redact(result["details"]))
        return {"error": result}
    return {
        "error": {
            "code": "internal_error",
            "message": "internal server error",
            **({"request_id": request_id} if request_id is not None else {}),
        }
    }


def validation_payload(*, request_id: str | None = None) -> dict[str, Any]:
    """Safe 422 envelope for FastAPI/Pydantic request validation failures."""

    return {
        "error": {
            "code": "validation_error",
            "message": "invalid request",
            **({"request_id": request_id} if request_id is not None else {}),
        }
    }


__all__ = ["error_payload", "status_for_error", "validation_payload"]
