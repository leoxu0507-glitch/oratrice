"""Public domain-error boundary for the Oratrice core.

Concrete adapters intentionally expose their own stable provider errors, but
frontends should only need to handle this small hierarchy.  Every error keeps
the original exception in ``cause`` for diagnostics while ``to_dict`` returns
safe, serialisable data (credentials and request content are redacted).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .observability import redact, redact_text


class OratriceError(RuntimeError):
    """Base exception crossing the core/application boundary."""

    code = "oratrice_error"

    def __init__(
        self,
        message: str,
        *,
        request_id: str | None = None,
        provider: str | None = None,
        operation: str | None = None,
        code: str | None = None,
        cause: BaseException | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        # Keep ``str(exc)`` useful for existing callers.  The message itself
        # is not logged automatically; to_dict applies the safe text filter.
        super().__init__(message)
        self.message = str(message)
        self.request_id = request_id
        self.provider = provider
        self.operation = operation
        self.code = code or type(self).code
        self.cause = cause
        self.details = dict(details or {})

    @property
    def reason(self) -> str:
        """Stable human-readable reason (alias for the historical message)."""

        return self.message

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code,
            "message": redact_text(self.message),
        }
        if self.request_id is not None:
            result["request_id"] = self.request_id
        if self.provider is not None:
            result["provider"] = self.provider
        if self.operation is not None:
            result["operation"] = self.operation
        if self.details:
            result["details"] = redact(self.details)
        return result

    as_dict = to_dict


class CoreError(OratriceError):
    code = "core_error"


class CoreRoutingError(CoreError):
    code = "routing_error"


class CoreProviderError(CoreError):
    code = "provider_error"


class CoreValidationError(CoreError):
    code = "validation_error"


class CoreRuntimeError(CoreError):
    code = "runtime_error"


class CoreConfigurationError(CoreError):
    code = "configuration_error"


class CoreHealthError(CoreError):
    code = "health_error"


class DependencyError(CoreError):
    """Base for failures in routing/provider/runtime dependencies."""

    code = "dependency_error"


DomainError = OratriceError
ApplicationError = CoreError
CoreFacadeError = CoreError


def error_from_exception(
    exc: BaseException,
    *,
    request_id: str | None = None,
    provider: str | None = None,
    operation: str | None = None,
    default: type[CoreError] = CoreError,
) -> CoreError:
    """Map a dependency exception to a stable core error.

    Existing core errors are returned unchanged unless missing correlation
    metadata needs to be filled in.  Provider errors preserve their code and
    details; no provider SDK type is exposed to the caller.
    """

    if isinstance(exc, CoreError):
        if request_id is None and provider is None and operation is None:
            return exc
        return type(exc)(
            exc.message,
            request_id=exc.request_id or request_id,
            provider=exc.provider or provider,
            operation=exc.operation or operation,
            code=exc.code,
            cause=exc.cause or exc,
            details=exc.details,
        )

    code = getattr(exc, "code", None)
    details = getattr(exc, "details", None)
    if not isinstance(details, Mapping):
        details = None
    # ProviderError subclasses carry a meaningful code and can be classified
    # without importing providers at module import time.
    if hasattr(exc, "provider") or str(code or "").startswith(("provider", "timeout", "unavailable")):
        target: type[CoreError] = CoreProviderError
    elif str(code or "").startswith("route"):
        target = CoreRoutingError
    else:
        target = default
    return target(
        str(exc),
        request_id=request_id,
        provider=provider or getattr(exc, "provider", None),
        operation=operation,
        code=code if isinstance(code, str) else None,
        cause=exc,
        details=details,
    )


__all__ = [
    "CoreConfigurationError",
    "CoreError",
    "CoreHealthError",
    "CoreProviderError",
    "CoreRoutingError",
    "CoreRuntimeError",
    "CoreValidationError",
    "ApplicationError",
    "CoreFacadeError",
    "DependencyError",
    "DomainError",
    "OratriceError",
    "error_from_exception",
]
