# -*- coding: utf-8 -*-
"""The stable, provider-neutral core facade.

``AIService`` used to own a concrete ``LlamaCppProvider`` instance.  That made
every frontend part of the transport layer and made routing impossible to
test without a running server.  The V1 facade below keeps the old positional
``chat(model_id, message)``/``stream(model_id, message)`` calls, but routes a
request first and resolves the selected provider through an injected registry.

The module intentionally imports only provider *contracts* (``ChatRequest``,
``ChatResponse`` and ``ChatChunk``).  Concrete adapters are selected by the
composition root and are never imported here.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
import inspect
import warnings
from typing import Any, Callable

from core.errors import (
    CoreError,
    CoreConfigurationError,
    CoreHealthError,
    CoreProviderError,
    CoreRoutingError,
    CoreRuntimeError,
    CoreValidationError,
)
from core.observability import HealthReport, get_logger, new_request_id, redact, request_context
from providers.base import (
    ChatChunk,
    ChatRequest,
    ChatResponse,
    ProviderError,
    content_has_image,
    content_to_text,
    normalize_content,
)
from router import RouteDecision, RouterRequest, StaticRouter, coerce_request


def _new_request_id(factory: Callable[[], str] | None = None) -> str:
    return new_request_id(factory)


def _value(resource: Any, key: str, default: Any = None) -> Any:
    """Read a config/resource field without depending on its concrete type."""

    if resource is None:
        return default
    getter = getattr(resource, "get", None)
    if callable(getter):
        try:
            result = getter(key, default)
        except TypeError:
            result = getter(key)
        if result is not None:
            return result
    if isinstance(resource, Mapping):
        return resource.get(key, default)
    return getattr(resource, key, default)


def _is_running(status: Any) -> bool:
    if isinstance(status, str):
        return status.lower() in {"running", "ready", "starting"}
    value = getattr(status, "state", status)
    value = getattr(value, "value", value)
    return str(value).lower() in {"running", "ready", "starting"}


def _response_text(value: Any) -> str:
    """Extract response text while dropping any structured image source."""

    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        try:
            return content_to_text(normalize_content(value))
        except (TypeError, ValueError):
            return ""
    if isinstance(value, Mapping):
        nested = value.get("content", value.get("text", ""))
        if nested is value:
            return ""
        return _response_text(nested)
    return str(value or "")


def _response(value: Any, *, request: ChatRequest, provider_id: str | None) -> ChatResponse:
    """Normalise common provider result shapes into ``ChatResponse``."""

    if isinstance(value, ChatResponse):
        if value.provider is None and provider_id is not None:
            return ChatResponse(
                content=value.content,
                model=value.model or request.model,
                finish_reason=value.finish_reason,
                usage=value.usage,
                provider=provider_id,
                request_id=value.request_id,
                raw=value.raw,
                metadata=value.metadata,
            )
        return value
    if isinstance(value, Mapping):
        content = value.get("content", value.get("text", value.get("message", "")))
        if isinstance(content, Mapping):
            content = content.get("content", content.get("text", ""))
        return ChatResponse(
            content=_response_text(content),
            model=value.get("model", request.model),
            finish_reason=value.get("finish_reason"),
            usage=value.get("usage") or {},
            provider=value.get("provider", provider_id),
            request_id=value.get("request_id", value.get("id")),
            raw=value,
            metadata=value.get("metadata") or {},
        )
    if isinstance(value, str):
        return ChatResponse(content=value, model=request.model, provider=provider_id, raw=value)
    content = getattr(value, "content", getattr(value, "text", None))
    if content is not None:
        return ChatResponse(
            content=_response_text(content),
            model=getattr(value, "model", request.model),
            finish_reason=getattr(value, "finish_reason", None),
            usage=getattr(value, "usage", {}) or {},
            provider=getattr(value, "provider", provider_id),
            request_id=getattr(value, "request_id", None),
            raw=value,
        )
    raise TypeError(f"provider returned unsupported chat result: {type(value).__name__}")


def _chunk(value: Any, *, request: ChatRequest, provider_id: str | None, index: int) -> ChatChunk:
    """Normalise one streaming item into ``ChatChunk``."""

    if isinstance(value, ChatChunk):
        if value.provider is None and provider_id is not None:
            return ChatChunk(
                content=value.content,
                model=value.model or request.model,
                index=value.index if value.index is not None else index,
                finish_reason=value.finish_reason,
                provider=provider_id,
                request_id=value.request_id,
                usage=value.usage,
                raw=value.raw,
            )
        return value
    if isinstance(value, Mapping):
        content = value.get("content", value.get("text", value.get("delta", "")))
        return ChatChunk(
            content=_response_text(content),
            model=value.get("model", request.model),
            index=value.get("index", index),
            finish_reason=value.get("finish_reason"),
            provider=value.get("provider", provider_id),
            request_id=value.get("request_id", value.get("id")),
            usage=value.get("usage") or {},
            raw=value,
        )
    if isinstance(value, str):
        return ChatChunk(content=value, model=request.model, index=index, provider=provider_id, raw=value)
    content = getattr(value, "content", getattr(value, "text", getattr(value, "delta", None)))
    if content is not None:
        return ChatChunk(
            content=_response_text(content),
            model=getattr(value, "model", request.model),
            index=getattr(value, "index", index),
            finish_reason=getattr(value, "finish_reason", None),
            provider=getattr(value, "provider", provider_id),
            request_id=getattr(value, "request_id", None),
            usage=getattr(value, "usage", {}) or {},
            raw=value,
        )
    raise TypeError(f"provider returned unsupported stream item: {type(value).__name__}")


def _call_legacy_or_canonical(method: Callable[..., Any], request: ChatRequest) -> Any:
    """Call both generations of the provider port without duplicate requests."""

    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return method(request)
    positional = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind
        in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
    ]
    first = positional[0] if positional else None
    # Canonical adapters name their first argument request/request_or_model and
    # accept one object.  This also handles the llama.cpp compatibility adapter.
    if first is None or first.name in {"request", "request_or_model", "chat_request"}:
        return method(request)
    # A pre-V1 adapter expects ``model, message``.  Keep generation options
    # keyword-only and only pass names accepted by the callable.
    kwargs = request.to_dict()
    kwargs.pop("model", None)
    kwargs.pop("messages", None)
    kwargs.pop("stream", None)
    kwargs["temperature"] = request.temperature
    if request.timeout is not None:
        kwargs["timeout"] = request.timeout
    kwargs.update(request.options)
    accepts_var_kw = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    if not accepts_var_kw:
        kwargs = {key: value for key, value in kwargs.items() if key in signature.parameters}
    return method(request.model, request.message, **kwargs)


class CoreFacade:
    """Stable core port shared by CLI, desktop, and future web frontends."""

    def __init__(
        self,
        *,
        manager: Any = None,
        provider_registry: Any = None,
        router: Any = None,
        configuration: Any = None,
        registry: Any = None,
        provider_configs: Mapping[str, Any] | None = None,
        provider_instances: Mapping[str, Any] | None = None,
        auto_start: bool = True,
        request_id_factory: Callable[[], str] | None = None,
        default_model: str | None = None,
        default_provider: str | None = None,
        logger: Any = None,
        observability: Any = None,
    ) -> None:
        self.manager = manager
        self.runtime_manager = getattr(manager, "runtime_manager", manager)
        self.provider_registry = provider_registry
        self.router = router
        self.configuration = configuration
        self.registry = registry
        self.provider_configs = dict(provider_configs or {})
        self.provider_instances = dict(provider_instances or {})
        self.auto_start = bool(auto_start)
        self.request_id_factory = request_id_factory
        self.default_model = default_model
        self.default_provider = default_provider
        # ``logger`` is injectable for embedding/tests.  ``observability`` is
        # accepted as a descriptive alias for callers that inject a logger
        # bundle from the composition root.
        self.logger = logger or observability or get_logger("oratrice.core")
        self._providers: dict[str, Any] = dict(self.provider_instances)

    def _log(self, level: str, event: str, *, request_id: str | None = None, **fields: Any) -> None:
        """Emit a safe structured event without affecting request behaviour."""

        logger = self.logger
        try:
            method = getattr(logger, level, None)
            if callable(method):
                method(event, request_id=request_id, **fields)
        except Exception:
            # Observability must never turn a successful chat into a failure.
            return

    # ``service`` is a friendly spelling used by a few integrations.
    @property
    def service(self) -> "CoreFacade":
        return self

    @staticmethod
    def _request_args(
        model_id: str | None,
        message: Any,
        kwargs: dict[str, Any],
    ) -> tuple[str | None, Any, dict[str, Any]]:
        # Canonical ``facade.chat(message, model="...")`` and historical
        # ``facade.chat(model_id, message)`` are both accepted.
        requested_model = kwargs.pop("model", kwargs.pop("model_id", None))
        if requested_model is None and isinstance(model_id, str):
            requested_model = model_id
        if message is None:
            if model_id is None:
                raise CoreValidationError("message is required")
            if isinstance(model_id, (list, tuple)):
                # A structured message may be supplied as the sole positional
                # argument; model then comes from ``model=``/defaults.
                message = model_id
            else:
                message = str(model_id)
        # Structured content is validated by ChatRequest.  Keep this boundary
        # opaque so image URLs/data never enter router logs or exceptions.
        if not isinstance(message, (str, list, tuple)):
            raise CoreValidationError("message must be text or structured content")
        try:
            message = normalize_content(message)
        except (TypeError, ValueError):
            # Validation diagnostics intentionally do not include prompt or
            # image source values.
            raise CoreValidationError("invalid message content") from None
        return requested_model, message, kwargs

    def _router_request(self, model_id: str | None, message: Any, kwargs: Mapping[str, Any]) -> RouterRequest:
        metadata = kwargs.get("metadata")
        metadata = dict(metadata or {}) if isinstance(metadata, Mapping) else {}
        route_text = content_to_text(message)
        return RouterRequest(
            message=route_text,
            model=model_id,
            provider=kwargs.get("provider"),
            capabilities=kwargs.get("capabilities"),
            requires_vision=bool(
                kwargs.get("requires_vision", kwargs.get("vision", False))
                or content_has_image(message)
            ),
            requires_network=bool(kwargs.get("requires_network", kwargs.get("network", False))),
            requires_tools=bool(kwargs.get("requires_tools", kwargs.get("tools", False))),
            metadata=metadata,
        )

    def _route(self, request: RouterRequest, request_id: str) -> RouteDecision:
        if self.router is None:
            # A directly constructed compatibility facade can still operate
            # with a provider object; the composition root always injects a
            # real router.
            provider = self.default_provider or "default"
            model = request.model or self.default_model or "default"
            return RouteDecision(model=model, provider=provider, reason="compatibility default")
        try:
            route = self.router.route(request)
            if isinstance(route, Mapping):
                route = RouteDecision.from_mapping(route)
            if not isinstance(route, RouteDecision):
                raise TypeError("router returned an invalid route decision")
            return route
        except CoreError:
            raise
        except Exception as exc:
            raise CoreRoutingError(
                f"route selection failed: {exc}", request_id=request_id, cause=exc,
                operation="route",
            ) from exc

    @staticmethod
    def _route_error_with_context(exc: CoreError, request_id: str) -> CoreError:
        """Attach the route operation and correlation ID to facade errors."""

        if exc.request_id == request_id and exc.operation == "route":
            return exc
        return type(exc)(
            exc.message,
            request_id=request_id,
            provider=exc.provider,
            operation="route",
            code=exc.code,
            cause=exc.cause,
            details=exc.details,
        )

    def route(
        self,
        model_id: str | None = None,
        message: Any = None,
        *,
        request_id: str | None = None,
        **kwargs: Any,
    ) -> RouteDecision:
        """Select a route without starting a runtime or invoking a provider.

        This is the public, provider-neutral route inspection port used by an
        HTTP/API adapter.  It deliberately stops after ``_route``: provider
        construction, runtime lifecycle, and model invocation belong only to
        :meth:`chat` and :meth:`stream`.
        """

        rid = request_id or _new_request_id(self.request_id_factory)
        self._log(
            "info",
            "core.request.start",
            request_id=rid,
            operation="route",
            model=model_id or kwargs.get("model") or kwargs.get("model_id") or self.default_model,
        )
        with request_context(rid):
            try:
                model_id, message, kwargs = self._request_args(model_id, message, dict(kwargs))
                request = self._router_request(model_id or self.default_model, message, kwargs)
                decision = self._route(request, rid)
                self._log(
                    "debug",
                    "core.request.routed",
                    request_id=rid,
                    operation="route",
                    model=decision.model,
                    provider=decision.provider,
                )
                self._log(
                    "info",
                    "core.request.completed",
                    request_id=rid,
                    operation="route",
                    model=decision.model,
                    provider=decision.provider,
                )
                return decision
            except CoreError as exc:
                wrapped = self._route_error_with_context(exc, rid)
                self._log(
                    "error",
                    "core.request.failed",
                    request_id=rid,
                    operation="route",
                    error_code=wrapped.code,
                    error_type=type(wrapped).__name__,
                )
                if wrapped is exc:
                    raise
                raise wrapped from exc
            except Exception as exc:
                wrapped = CoreRoutingError(
                    f"route selection failed: {exc}",
                    request_id=rid,
                    cause=exc,
                    operation="route",
                )
                self._log(
                    "error",
                    "core.request.failed",
                    request_id=rid,
                    operation="route",
                    error_code=wrapped.code,
                    error_type=type(wrapped).__name__,
                )
                raise wrapped from exc

    def _provider_config(self, provider_id: str) -> Mapping[str, Any]:
        value = self.provider_configs.get(provider_id)
        if value is None:
            return {"id": provider_id, "provider_id": provider_id, "type": provider_id}
        if isinstance(value, Mapping):
            result = dict(value)
        else:
            result = dict(getattr(value, "__dict__", {}))
        options = result.pop("options", None)
        if isinstance(options, Mapping):
            merged = dict(options)
            merged.update(result)
            result = merged
        result.setdefault("id", provider_id)
        result.setdefault("provider_id", provider_id)
        return result

    def _provider(self, provider_id: str, request_id: str) -> Any:
        if provider_id in self._providers:
            return self._providers[provider_id]
        if self.provider_registry is None:
            raise CoreProviderError(
                f"provider {provider_id!r} is not configured",
                request_id=request_id,
                provider=provider_id,
            )
        config = self._provider_config(provider_id)
        provider_type = config.get("type", config.get("driver", provider_id))
        try:
            creator = getattr(self.provider_registry, "create", None)
            if not callable(creator):
                creator = getattr(self.provider_registry, "build", None)
            if not callable(creator):
                raise TypeError("provider registry has no create/build method")
            instance = creator(provider_type, config)
        except CoreError:
            raise
        except Exception as exc:
            raise CoreProviderError(
                f"could not construct provider {provider_id!r}: {exc}",
                request_id=request_id,
                provider=provider_id,
                cause=exc,
                operation="provider_init",
            ) from exc
        self._providers[provider_id] = instance
        return instance

    def _canonical_model_id(self, model_id: str | None) -> str | None:
        """Resolve a provider/gateway model alias to one configured model ID.

        Route decisions intentionally carry the model string expected by the
        selected provider (for example, a LiteLLM gateway alias).  Runtime and
        registry operations, however, address the canonical model resource.
        Keep this resolver pure: it only inspects the validated configuration,
        never mutates it, and leaves an unknown value untouched for compatibility
        with injected/legacy configurations.
        """

        if model_id is None:
            return None
        models = getattr(self.configuration, "models", None)
        if not isinstance(models, Mapping):
            return model_id

        matched: set[str] = set()
        for key, model in models.items():
            canonical_value = _value(model, "id")
            if not isinstance(canonical_value, str) or not canonical_value.strip():
                canonical_value = str(key)
            canonical = canonical_value.strip()
            candidates = (
                key,
                canonical_value,
                _value(model, "alias"),
                _value(model, "gateway_alias"),
            )
            if any(
                isinstance(candidate, str) and candidate.strip() == model_id
                for candidate in candidates
            ):
                matched.add(canonical)

        if len(matched) > 1:
            choices = ", ".join(sorted(matched))
            raise CoreConfigurationError(
                f"model alias {model_id!r} resolves to multiple configured models: {choices}"
            )
        return next(iter(matched), model_id)

    def _resource(self, model_id: str | None) -> Any:
        if model_id is None:
            return None
        if self.registry is not None:
            getter = getattr(self.registry, "get", None)
            if callable(getter):
                try:
                    value = getter(model_id)
                except Exception:
                    value = None
                if value is not None:
                    return value
        if self.configuration is not None:
            getter = getattr(self.configuration, "get_model", None)
            if callable(getter):
                return getter(model_id)
        return None

    def _ensure_runtime(self, model_id: str | None, request_id: str) -> None:
        if not self.auto_start or self.manager is None or model_id is None:
            return
        runtime_model_id = self._canonical_model_id(model_id)
        # ResourceManager compatibility path (the composition root uses it to
        # pair the resource registry with RuntimeManager).
        status_model = getattr(self.manager, "status_model", None)
        start_model = getattr(self.manager, "start_model", None)
        if callable(status_model) and callable(start_model):
            try:
                if not _is_running(status_model(runtime_model_id)):
                    start_model(runtime_model_id)
            except CoreError:
                raise
            except Exception as exc:
                raise CoreProviderError(
                    f"runtime for model {runtime_model_id!r} could not be started: {exc}",
                    request_id=request_id,
                    cause=exc,
                    operation="runtime_start",
                ) from exc
            return

        # A bare RuntimeManager can still be injected for small integrations.
        runtime = _value(self._resource(runtime_model_id), "runtime") or _value(
            self._resource(runtime_model_id), "runtime_id"
        )
        if runtime is None:
            return
        runtime_resource = self._resource(str(runtime)) or runtime
        status = getattr(self.manager, "status", None)
        start = getattr(self.manager, "start", None)
        if callable(status) and callable(start):
            try:
                if not _is_running(status(runtime_resource)):
                    start(runtime_resource)
            except Exception as exc:
                raise CoreProviderError(
                    f"runtime for model {model_id!r} could not be started: {exc}",
                    request_id=request_id,
                    cause=exc,
                    operation="runtime_start",
                ) from exc

    @staticmethod
    def _health_component(value: Any, *, component_id: str) -> dict[str, Any]:
        """Normalise a provider/runtime health value to safe mapping data."""

        if isinstance(value, HealthReport):
            result = value.to_dict()
        elif isinstance(value, Mapping):
            result = dict(value)
        else:
            result = {}
            status = getattr(value, "status", None)
            state = getattr(value, "state", None)
            if status is None:
                status = getattr(state, "value", state)
            if status is not None:
                result["status"] = str(status)
            for key in ("healthy", "ok", "is_healthy", "returncode", "error", "runtime_id", "provider"):
                item = getattr(value, key, None)
                if item is not None:
                    result[key] = item
        status = str(result.get("status", result.get("state", "unknown"))).lower()
        if "healthy" not in result:
            healthy = result.get("ok", result.get("is_healthy"))
            if healthy is None:
                healthy = status in {"ok", "healthy", "ready", "up", "running"}
            result["healthy"] = bool(healthy)
        result.setdefault("status", status)
        result.setdefault("component", component_id)
        # Health payloads are diagnostics, but provider implementations may
        # include adapter metadata.  Keep the report serialisable and secret-
        # free just as logs are.
        return redact(result)

    def _provider_health(self, provider_id: str, provider: Any, request_id: str) -> dict[str, Any]:
        try:
            checker = getattr(provider, "health_status", None)
            if not callable(checker):
                checker = getattr(provider, "check_health", None)
            if not callable(checker):
                checker = getattr(provider, "health", None)
            if not callable(checker):
                raise TypeError("provider has no health/check_health method")
            return self._health_component(checker(), component_id=provider_id)
        except Exception as exc:
            self._log("warning", "core.health.provider_error", request_id=request_id, provider=provider_id, error_type=type(exc).__name__)
            return {
                "component": provider_id,
                "status": "unhealthy",
                "healthy": False,
                "error_code": getattr(exc, "code", "health_error"),
                "error_type": type(exc).__name__,
            }

    def _runtime_health(self, runtime_id: str, runtime: Any, request_id: str) -> dict[str, Any]:
        try:
            checker = getattr(runtime, "health", None)
            if callable(checker):
                return self._health_component(checker(), component_id=runtime_id)
            checker = getattr(runtime, "status_info", None) or getattr(runtime, "status", None)
            if not callable(checker):
                raise TypeError("runtime manager has no status/health method")
            return self._health_component(checker(runtime_id), component_id=runtime_id)
        except Exception as exc:
            self._log("warning", "core.health.runtime_error", request_id=request_id, runtime=runtime_id, error_type=type(exc).__name__)
            return {
                "component": runtime_id,
                "status": "unhealthy",
                "healthy": False,
                "error_code": getattr(exc, "code", "health_error"),
                "error_type": type(exc).__name__,
            }

    def health(self, *, request_id: str | None = None, include_configured: bool = True) -> HealthReport:
        """Aggregate provider and runtime health without exposing payloads.

        Existing provider instances are checked; configured-but-lazy providers
        are represented as ``unknown`` and are not constructed merely by
        asking for health.  Runtime records/configured resources are queried
        through their injected manager.  A failed individual probe is captured
        as an unhealthy component so one broken dependency does not hide the
        health of the rest of the graph.
        """

        rid = request_id or _new_request_id(self.request_id_factory)
        providers: dict[str, dict[str, Any]] = {}
        provider_ids = set(self._providers)
        if include_configured:
            provider_ids.update(self.provider_configs)
        for provider_id in sorted(str(item) for item in provider_ids):
            provider = self._providers.get(provider_id)
            if provider is None:
                providers[provider_id] = {
                    "component": provider_id,
                    "status": "unknown",
                    "healthy": False,
                    "lazy": True,
                }
            else:
                providers[provider_id] = self._provider_health(provider_id, provider, rid)

        runtimes: dict[str, dict[str, Any]] = {}
        runtime_manager = self.runtime_manager
        records = getattr(runtime_manager, "_records", None)
        runtime_ids: set[str] = set(records) if isinstance(records, Mapping) else set()
        if include_configured and self.manager is not None:
            try:
                list_runtimes = getattr(self.manager, "list_runtimes", None)
                if callable(list_runtimes):
                    for runtime in list_runtimes() or ():
                        value = _value(runtime, "id") or _value(runtime, "runtime_id")
                        if value is not None:
                            runtime_ids.add(str(value))
            except Exception:
                pass
        for runtime_id in sorted(runtime_ids):
            runtimes[runtime_id] = self._runtime_health(runtime_id, runtime_manager, rid)

        components = {"providers": providers, "runtimes": runtimes}
        statuses = [item for group in components.values() for item in group.values()]
        if statuses and all(bool(item.get("healthy")) for item in statuses):
            status = "healthy"
        elif any(item.get("status") in {"unhealthy", "failed", "timeout", "stopped", "exited"} or item.get("healthy") is False for item in statuses):
            status = "unhealthy"
        else:
            status = "unknown"
        report = HealthReport(status=status, components=components, request_id=rid)
        self._log("info", "core.health.checked", request_id=rid, status=status, provider_count=len(providers), runtime_count=len(runtimes))
        return report

    # Descriptive aliases used by health endpoints and older integrations.
    health_check = health
    check_health = health
    health_status = health

    def _chat_request(
        self,
        model: str,
        message: Any,
        kwargs: Mapping[str, Any],
        *,
        stream: bool,
    ) -> ChatRequest:
        reserved = {
            "provider",
            "capabilities",
            "requires_vision",
            "requires_network",
            "requires_tools",
            "vision",
            "network",
            "tools",
            "metadata",
            "model",
            "model_id",
            "stream",
        }
        values = {key: value for key, value in kwargs.items() if key not in reserved}
        metadata = kwargs.get("metadata")
        return ChatRequest(
            model=model,
            message=message,
            stream=stream,
            metadata=metadata if isinstance(metadata, Mapping) else None,
            **values,
        )

    def chat(self, model_id: str | None = None, message: str | None = None, **kwargs: Any) -> ChatResponse:
        model_id, message, kwargs = self._request_args(model_id, message, kwargs)
        request_id = _new_request_id(self.request_id_factory)
        self._log("info", "core.request.start", request_id=request_id, operation="chat", model=model_id or self.default_model)
        with request_context(request_id):
            provider_id: str | None = None
            try:
                request = self._router_request(model_id or self.default_model, message, kwargs)
                decision = self._route(request, request_id)
                provider_id = decision.provider
                self._log("debug", "core.request.routed", request_id=request_id, operation="chat", model=decision.model, provider=provider_id)
                self._ensure_runtime(decision.model or model_id, request_id)
                provider = self._provider(provider_id, request_id)
                chat_request = self._chat_request(decision.model or model_id or "default", message, kwargs, stream=False)
                result = _call_legacy_or_canonical(getattr(provider, "chat"), chat_request)
                response = _response(result, request=chat_request, provider_id=provider_id)
                if response.request_id is None:
                    response = ChatResponse(
                        content=response.content,
                        model=response.model,
                        finish_reason=response.finish_reason,
                        usage=response.usage,
                        provider=response.provider or provider_id,
                        request_id=request_id,
                        raw=response.raw,
                        metadata=response.metadata,
                    )
                self._log("info", "core.request.completed", request_id=request_id, operation="chat", provider=provider_id, model=response.model)
                return response
            except CoreError as exc:
                self._log("error", "core.request.failed", request_id=request_id, operation="chat", provider=provider_id, error_code=exc.code, error_type=type(exc).__name__)
                raise
            except ProviderError as exc:
                wrapped = CoreProviderError(
                    str(exc), request_id=request_id, provider=provider_id, cause=exc,
                    details=getattr(exc, "details", None), operation="chat",
                )
                self._log("error", "core.request.failed", request_id=request_id, operation="chat", provider=provider_id, error_code=wrapped.code, error_type=type(wrapped).__name__)
                raise wrapped from exc
            except Exception as exc:
                wrapped = CoreProviderError(
                    f"provider {provider_id!r} chat failed: {exc}",
                    request_id=request_id,
                    provider=provider_id,
                    cause=exc,
                    operation="chat",
                )
                self._log("error", "core.request.failed", request_id=request_id, operation="chat", provider=provider_id, error_code=wrapped.code, error_type=type(wrapped).__name__)
                raise wrapped from exc

    def stream(self, model_id: str | None = None, message: str | None = None, **kwargs: Any) -> Iterator[ChatChunk]:
        model_id, message, kwargs = self._request_args(model_id, message, kwargs)
        request_id = _new_request_id(self.request_id_factory)
        self._log("info", "core.request.start", request_id=request_id, operation="stream", model=model_id or self.default_model)
        # Routing/provider resolution happens at call time, as before; the
        # returned iterator binds the same id while chunks are consumed.
        with request_context(request_id):
            provider_id: str | None = None
            try:
                request = self._router_request(model_id or self.default_model, message, kwargs)
                decision = self._route(request, request_id)
                provider_id = decision.provider
                self._log("debug", "core.request.routed", request_id=request_id, operation="stream", model=decision.model, provider=provider_id)
                self._ensure_runtime(decision.model or model_id, request_id)
                provider = self._provider(provider_id, request_id)
                chat_request = self._chat_request(decision.model or model_id or "default", message, kwargs, stream=True)
            except CoreError as exc:
                self._log("error", "core.request.failed", request_id=request_id, operation="stream", provider=provider_id, error_code=exc.code, error_type=type(exc).__name__)
                raise
            except Exception as exc:
                wrapped = CoreProviderError(
                    f"provider {provider_id!r} stream setup failed: {exc}",
                    request_id=request_id,
                    provider=provider_id,
                    cause=exc,
                    operation="stream",
                )
                self._log("error", "core.request.failed", request_id=request_id, operation="stream", provider=provider_id, error_code=wrapped.code, error_type=type(wrapped).__name__)
                raise wrapped from exc

        def iterate() -> Iterator[ChatChunk]:
            with request_context(request_id):
                try:
                    values = _call_legacy_or_canonical(getattr(provider, "stream"), chat_request)
                    for index, value in enumerate(values):
                        yield _chunk(value, request=chat_request, provider_id=provider_id, index=index)
                    self._log("info", "core.request.completed", request_id=request_id, operation="stream", provider=provider_id, model=chat_request.model)
                except CoreError as exc:
                    self._log("error", "core.request.failed", request_id=request_id, operation="stream", provider=provider_id, error_code=exc.code, error_type=type(exc).__name__)
                    raise
                except ProviderError as exc:
                    wrapped = CoreProviderError(
                        str(exc), request_id=request_id, provider=provider_id, cause=exc,
                        details=getattr(exc, "details", None), operation="stream",
                    )
                    self._log("error", "core.request.failed", request_id=request_id, operation="stream", provider=provider_id, error_code=wrapped.code, error_type=type(wrapped).__name__)
                    raise wrapped from exc
                except Exception as exc:
                    wrapped = CoreProviderError(
                        f"provider {provider_id!r} stream failed: {exc}",
                        request_id=request_id,
                        provider=provider_id,
                        cause=exc,
                        operation="stream",
                    )
                    self._log("error", "core.request.failed", request_id=request_id, operation="stream", provider=provider_id, error_code=wrapped.code, error_type=type(wrapped).__name__)
                    raise wrapped from exc

        return iterate()


class _LegacyRouter:
    """Tiny router used only by the direct ``AIService(manager, provider)`` shim."""

    def __init__(self, provider_id: str = "default") -> None:
        self.provider_id = provider_id

    def route(self, request: RouterRequest) -> RouteDecision:
        return RouteDecision(
            model=request.model or "default",
            provider=self.provider_id,
            reason="legacy AIService compatibility",
        )


class AIService(CoreFacade):
    """Compatibility shim for the pre-V1 ``AIService`` constructor.

    New code should receive :class:`CoreFacade` from ``core.application``.  A
    direct construction remains valid for one migration window and preserves
    string return values/chunk values expected by the old CLI.
    """

    def __init__(
        self,
        manager: Any = None,
        provider: Any = None,
        *,
        router: Any = None,
        provider_registry: Any = None,
        provider_configs: Mapping[str, Any] | None = None,
        provider_instances: Mapping[str, Any] | None = None,
        configuration: Any = None,
        registry: Any = None,
        auto_start: bool = True,
        _suppress_warning: bool = False,
        default_model: str | None = None,
        default_provider: str | None = None,
        **kwargs: Any,
    ) -> None:
        if not _suppress_warning:
            warnings.warn(
                "AIService is a compatibility shim; inject CoreFacade from core.application",
                DeprecationWarning,
                stacklevel=2,
            )
        instances = dict(provider_instances or {})
        compat_provider_id = "default"
        if provider is not None:
            instances.setdefault(compat_provider_id, provider)
        super().__init__(
            manager=manager,
            provider_registry=provider_registry,
            router=router or _LegacyRouter(compat_provider_id),
            configuration=configuration,
            registry=registry,
            provider_configs=provider_configs,
            provider_instances=instances,
            auto_start=auto_start,
            default_model=default_model,
            default_provider=default_provider or compat_provider_id,
            **kwargs,
        )

    def chat(self, model_id: str | None = None, message: str | None = None, **kwargs: Any) -> str:
        return super().chat(model_id, message, **kwargs).content

    def stream(self, model_id: str | None = None, message: str | None = None, **kwargs: Any) -> Iterator[str]:
        for chunk in super().stream(model_id, message, **kwargs):
            yield chunk.content


# Friendly aliases used by application/frontends and by early V1 callers.
ApplicationFacade = CoreFacade
Facade = CoreFacade


__all__ = [
    "AIService",
    "ApplicationFacade",
    "CoreError",
    "CoreConfigurationError",
    "CoreFacade",
    "CoreHealthError",
    "CoreProviderError",
    "CoreRoutingError",
    "CoreRuntimeError",
    "CoreValidationError",
    "Facade",
]
