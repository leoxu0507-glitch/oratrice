"""Router ports and deterministic/static routing implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from .contracts import (
    RouteCapabilityError,
    RouteDecision,
    RouteNotFoundError,
    RouteValidationError,
    RouterRequest,
    coerce_request,
)


@runtime_checkable
class RouterProtocol(Protocol):
    """Minimal dependency-injection port consumed by a core facade."""

    def route(self, request: RouterRequest) -> RouteDecision:
        ...


class Router(ABC):
    """Convenience base class implementing ``router(request)`` syntax."""

    @abstractmethod
    def route(self, request: RouterRequest) -> RouteDecision:
        """Return a decision without invoking the selected provider."""

    def __call__(self, request: RouterRequest) -> RouteDecision:
        return self.route(request)


# The name ``BaseRouter`` is retained as a friendly alias for integrations that
# prefer the explicit base-class spelling.
BaseRouter = Router


def _decision(value: RouteDecision | Mapping[str, Any], label: str) -> RouteDecision:
    if isinstance(value, RouteDecision):
        return value
    if isinstance(value, Mapping):
        try:
            return RouteDecision.from_mapping(value)
        except Exception as exc:
            raise RouteValidationError(f"invalid {label}: {exc}") from exc
    raise RouteValidationError(f"{label} must be RouteDecision or an object")


class StaticRouter(Router):
    """Pure deterministic router for local-first defaults and fault policy.

    ``routes`` is a mapping from an opaque request model ID to a decision.
    ``default`` is used when a request has no model or matches the default
    model.  A ``fallback`` may be supplied for explicit fault handling, but it
    is only considered when ``allow_cloud_fallback`` is true (or when no cloud
    provider set was supplied and the caller explicitly asks for fallback).
    The class does no availability checks: a provider manager remains the
    owner of health, lifecycle, and retry behavior.
    """

    def __init__(
        self,
        routes: Mapping[str, RouteDecision | Mapping[str, Any]] | None = None,
        default: RouteDecision | Mapping[str, Any] | None = None,
        *,
        fallback: RouteDecision | Mapping[str, Any] | None = None,
        allow_cloud_fallback: bool = False,
        allow_cloud: bool | None = None,
        local_first: bool = True,
        local_providers: Iterable[str] | None = None,
        cloud_providers: Iterable[str] | None = None,
        default_model: str | None = None,
        default_provider: str | None = None,
    ) -> None:
        if routes is None:
            routes = {}
        if not isinstance(routes, Mapping):
            raise RouteValidationError("routes must be a mapping")
        self.routes: dict[str, RouteDecision] = {}
        for key, value in routes.items():
            if not isinstance(key, str) or not key.strip():
                raise RouteValidationError("route keys must be non-empty strings")
            self.routes[key.strip()] = _decision(value, f"route {key!r}")

        if default is None and default_model is not None and default_provider is not None:
            default = RouteDecision(
                model=default_model,
                provider=default_provider,
                reason="configured local-first default",
            )
        self.default = _decision(default, "default route") if default is not None else None
        self.fallback = _decision(fallback, "fallback route") if fallback is not None else None
        if allow_cloud is not None:
            allow_cloud_fallback = allow_cloud
        if not isinstance(allow_cloud_fallback, bool):
            raise RouteValidationError("allow_cloud_fallback must be a boolean")
        if not isinstance(local_first, bool):
            raise RouteValidationError("local_first must be a boolean")
        self.allow_cloud_fallback = allow_cloud_fallback
        self.local_first = local_first
        self.local_providers = frozenset(self._provider_set(local_providers, "local_providers"))
        self.cloud_providers = frozenset(self._provider_set(cloud_providers, "cloud_providers"))
        overlap = self.local_providers & self.cloud_providers
        if overlap:
            raise RouteValidationError(
                f"provider(s) cannot be both local and cloud: {', '.join(sorted(overlap))}"
            )

    @staticmethod
    def _provider_set(values: Iterable[str] | None, label: str) -> set[str]:
        if values is None:
            return set()
        if isinstance(values, (str, bytes)):
            raise RouteValidationError(f"{label} must be an iterable of provider IDs")
        result: set[str] = set()
        for value in values:
            if not isinstance(value, str) or not value.strip():
                raise RouteValidationError(f"{label} must contain non-empty strings")
            result.add(value.strip())
        return result

    @property
    def default_decision(self) -> RouteDecision | None:
        return self.default

    def _is_cloud(self, decision: RouteDecision) -> bool:
        # Classification is injected; an unknown provider is not guessed to be
        # cloud and therefore remains usable for legacy/local configurations.
        return decision.provider in self.cloud_providers

    def _allowed_by_policy(self, decision: RouteDecision) -> bool:
        if self.local_first and self._is_cloud(decision) and not self.allow_cloud_fallback:
            return False
        return True

    @staticmethod
    def _matches_request(decision: RouteDecision, request: RouterRequest) -> bool:
        if request.model is not None and decision.model != request.model:
            return False
        if request.provider is not None and decision.provider != request.provider:
            return False
        return (
            (not request.requires_vision or decision.requires_vision)
            and (not request.requires_network or decision.requires_network)
            and (not request.requires_tools or decision.requires_tools)
        )

    def _candidate_for(self, request: RouterRequest) -> RouteDecision | None:
        if request.model is not None:
            candidate = self.routes.get(request.model)
            if candidate is not None:
                return candidate
        if request.provider is not None:
            # Provider IDs are accepted as keys as a convenience for callers
            # with a provider-specific route table.
            candidate = self.routes.get(request.provider)
            if candidate is not None:
                return candidate
        if request.model is None and request.provider is None:
            return self.default
        if self.default is not None and self._matches_request(self.default, request):
            return self.default
        return None

    def route(self, request: RouterRequest) -> RouteDecision:
        request = coerce_request(request)
        candidate = self._candidate_for(request)
        if candidate is not None and self._matches_request(candidate, request):
            if self._allowed_by_policy(candidate):
                return candidate
            candidate = None

        # A fallback is explicit and deterministic.  It is never selected just
        # because the primary provider is unavailable; that signal belongs to
        # the provider manager and must be represented by a separate request.
        if self.fallback is not None and self.allow_cloud_fallback:
            if self._matches_request(self.fallback, request) and self._allowed_by_policy(self.fallback):
                return self.fallback

        if candidate is not None:
            if request.requires_vision and not candidate.requires_vision:
                capability = "vision"
            elif request.requires_network and not candidate.requires_network:
                capability = "network"
            elif request.requires_tools and not candidate.requires_tools:
                capability = "tools"
            elif not self._allowed_by_policy(candidate):
                raise RouteNotFoundError(
                    f"route for provider {candidate.provider!r} is disabled by local-first policy"
                )
            else:
                capability = "requested constraints"
            raise RouteCapabilityError(
                f"route {candidate.model!r}/{candidate.provider!r} cannot satisfy {capability}"
            )

        requested = request.model or request.provider or "request"
        raise RouteNotFoundError(f"no configured route for {requested!r}")

    select = route


# A name used by a few compositions; keeping it an alias avoids a second
# implementation and keeps behavior deterministic.
DeterministicRouter = StaticRouter


__all__ = [
    "BaseRouter",
    "DeterministicRouter",
    "Router",
    "RouterProtocol",
    "StaticRouter",
]
