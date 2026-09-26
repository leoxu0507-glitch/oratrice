"""Composition root for the Oratrice V1 request path.

The application factory is deliberately the only place that chooses concrete
infrastructure.  Configuration is parsed here, registries and lifecycle
objects are wired here, and frontends receive the provider-neutral
``CoreFacade``.  Creating an application performs no network request and does
not start a runtime; providers are constructed lazily on the first request.

The module keeps a few descriptive aliases (``create_application``,
``bootstrap_application`` and ``bootstrap``) so CLI, desktop, and web callers
can migrate without coupling to a particular factory spelling.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.configuration import Configuration, ConfigurationLoader, ConfigurationError
from core.manager import ResourceManager
from core.registry import ResourceRegistry
from core.runtime_manager import RuntimeManager
from core.ai_service import AIService, CoreFacade
from providers.registry import ProviderRegistry, create_default_registry
from router import GemmaRouterProvider, RouteDecision, StaticRouter
from router.policy import RoutingPolicy


def _default_config_path() -> Path:
    """Choose the new contract first, retaining the legacy file fallback."""

    project_root = Path(__file__).resolve().parent.parent
    candidates = (
        project_root / "config" / "oratrice.yaml",
        project_root / "config" / "resources.yaml",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    # Let ``ConfigurationLoader`` produce its normal, source-qualified error.
    return candidates[0]


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    values = getattr(value, "__dict__", None)
    return dict(values) if isinstance(values, Mapping) else {}


class ApplicationRegistry(ResourceRegistry):
    """Resource registry backed by the validated configuration contract.

    ``ResourceRegistry`` remains the compatibility implementation for the old
    ``resources:`` YAML shape.  This subclass overlays the typed V1 sections
    (models, runtimes, providers, routes, policies) while retaining any legacy
    categories such as services/apps/system.  The overlay uses the same
    ``get``/``list_*`` methods expected by ``ResourceManager`` and therefore
    requires no changes to the runtime implementation.
    """

    def __init__(self, configuration: Configuration, legacy: ResourceRegistry | None = None):
        super().__init__()
        self.configuration = configuration
        self.legacy = legacy
        if legacy is not None:
            self.resources = {category: list(items) for category, items in legacy.resources.items()}
            self._by_id = dict(getattr(legacy, "_by_id", {}))

        # Dataclass config objects expose ``id``, ``name`` and ``get`` and are
        # intentionally suitable runtime resources.  They are not copied or
        # mutated, preserving the loader's immutable configuration contract.
        sections = {
            "models": configuration.models,
            "runtimes": configuration.runtimes,
            "providers": configuration.providers,
        }
        for category, values in sections.items():
            if values:
                self.resources[category] = list(values.values())
                for resource in values.values():
                    self._by_id[resource.id] = resource
        self.resources.setdefault("routes", list(configuration.routes.values()))
        self.resources.setdefault("policies", list(configuration.policies.values()))
        for resource in configuration.routes.values():
            self._by_id[resource.id] = resource
        for resource in configuration.policies.values():
            self._by_id[resource.id] = resource

    def get(self, resource_id: str, category: str | None = None):
        if category is None:
            resource = self._by_id.get(str(resource_id))
            if resource is not None:
                return resource
        return super().get(resource_id, category=category)

    def list_routes(self):
        return list(self.configuration.routes.values())

    def list_policies(self):
        return list(self.configuration.policies.values())

    def get_route(self, route_id: str):
        return self.configuration.get_route(route_id)

    def get_policy(self, policy_id: str):
        return self.configuration.get_policy(policy_id)


def _legacy_registry(path: Path) -> ResourceRegistry:
    registry = ResourceRegistry()
    # ``ResourceRegistry`` accepts both the legacy and V1 top-level files; for
    # V1 it simply leaves the compatibility categories empty.
    registry.load(path)
    return registry


def _config_object(config_path: Path | str | None, configuration: Configuration | None) -> Configuration:
    if configuration is not None:
        return configuration
    source = Path(config_path).expanduser() if config_path is not None else _default_config_path()
    return ConfigurationLoader(source).load()


def _provider_values(configuration: Configuration) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for provider_id, provider in configuration.providers.items():
        values = _mapping(provider)
        options = values.pop("options", None)
        if isinstance(options, Mapping):
            merged = dict(options)
            merged.update(values)
            values = merged
        values.setdefault("id", provider_id)
        values.setdefault("provider_id", provider_id)
        values.setdefault("type", "openai_compatible")
        result[provider_id] = values
    return result


def _default_provider_for_model(configuration: Configuration, model: Any) -> str:
    provider = getattr(model, "provider", None) or (model.get("provider") if isinstance(model, Mapping) else None)
    if provider:
        return str(provider)
    runtime_id = getattr(model, "runtime", None) or (model.get("runtime") if isinstance(model, Mapping) else None)
    runtime = configuration.runtimes.get(runtime_id) if runtime_id else None
    provider = getattr(runtime, "provider", None) if runtime is not None else None
    if provider:
        return str(provider)
    defaults = dict(configuration.defaults or {})
    for key in ("provider", "default_provider", "local_provider"):
        if defaults.get(key):
            return str(defaults[key])
    # Legacy resources did not have provider IDs.  This stable name maps to
    # the built-in llama.cpp alias in the default ProviderRegistry.
    return "llama_cpp"


def _provider_values_with_legacy_defaults(
    configuration: Configuration,
    provider_values: dict[str, Mapping[str, Any]],
    provider_registry: Any,
) -> dict[str, Mapping[str, Any]]:
    """Add lazy local defaults for ``resources.yaml`` configurations."""

    defaults = dict(configuration.defaults or {})
    endpoint = (
        defaults.get("base_url")
        or defaults.get("endpoint")
        or defaults.get("provider_base_url")
        or "http://127.0.0.1:8080"
    )
    provider_names = {
        _default_provider_for_model(configuration, model)
        for model in configuration.models.values()
    }
    provider_names.update(
        str(getattr(route, "provider", ""))
        for route in configuration.routes.values()
        if getattr(route, "provider", None)
    )
    for provider_id in provider_names:
        if provider_id in provider_values:
            continue
        provider_type = provider_id
        has = getattr(provider_registry, "has", None)
        if callable(has) and not has(provider_type):
            provider_type = "llama_cpp"
        provider_values[provider_id] = {
            "id": provider_id,
            "provider_id": provider_id,
            "type": provider_type,
            "base_url": endpoint,
        }
    return provider_values


def _merged_values(value: Any) -> dict[str, Any]:
    """Return config metadata and top-level fields as one shallow mapping."""

    values = _mapping(value)
    options = values.pop("options", None)
    if isinstance(options, Mapping):
        merged = dict(options)
        merged.update(values)
        values = merged
    return values


def _gateway_provider_id(configuration: Configuration, spec: Mapping[str, Any] | None = None) -> str | None:
    """Resolve the configured gateway provider without importing infrastructure."""

    defaults = _merged_values(configuration.defaults)
    gateway = defaults.get("gateway")
    gateway_values = _merged_values(gateway)
    router_values = _merged_values(spec)
    # ``defaults.router.provider`` names the local Gemma endpoint, whereas
    # ``defaults.gateway.provider`` names the selected response gateway.  Do
    # not confuse the two when deriving aliases or default allow-lists.
    for key in ("gateway_provider", "gateway_provider_id"):
        value = router_values.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in ("provider", "provider_id", "gateway_provider", "gateway_provider_id"):
        value = gateway_values.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    # A profile may omit ``defaults.gateway`` while still marking the provider
    # type explicitly.  Pick the first local LiteLLM/gateway registration.
    for provider_id, provider in configuration.providers.items():
        provider_values = _merged_values(provider)
        provider_type = str(provider_values.get("type", "")).lower()
        provider_name = str(provider_id).lower()
        if "litellm" in provider_type or "gateway" in provider_type or "litellm" in provider_name:
            return str(provider_id)
    return None


def _is_gateway_provider(
    configuration: Configuration,
    provider_id: str,
    spec: Mapping[str, Any] | None = None,
) -> bool:
    gateway_id = _gateway_provider_id(configuration, spec)
    if gateway_id and provider_id == gateway_id:
        return True
    provider = configuration.providers.get(provider_id)
    values = _merged_values(provider)
    provider_type = str(values.get("type", "")).lower()
    name = str(provider_id).lower()
    return "litellm" in provider_type or "gateway" in provider_type or "litellm" in name


def _gateway_model_alias(
    configuration: Configuration,
    model_id: str,
    provider_id: str,
    route: Any = None,
    spec: Mapping[str, Any] | None = None,
) -> str:
    """Map a configured model resource to the LiteLLM model alias.

    Route decisions intentionally carry opaque gateway aliases (``gpt_oss``
    and ``qwen_vl``), not the direct llama.cpp provider/model IDs.  Keeping the
    mapping in profile metadata lets the composition root perform that
    translation while the router and providers remain configuration-driven.
    """

    if not _is_gateway_provider(configuration, provider_id, spec):
        return model_id
    route_values = _merged_values(route)
    model_values = _merged_values(configuration.models.get(model_id))
    defaults = _merged_values(configuration.defaults)
    gateway_values = _merged_values(defaults.get("gateway"))
    aliases = gateway_values.get("model_aliases")
    if not isinstance(aliases, Mapping):
        aliases = {}
    candidates: list[Any] = [
        route_values.get("gateway_alias"),
        route_values.get("gateway_model"),
        route_values.get("model_alias"),
        model_values.get("gateway_alias"),
        model_values.get("gateway_model"),
        model_values.get("model_alias"),
        aliases.get(model_id),
        aliases.get(model_id.removeprefix("model.")),
        # ``alias`` is a useful fallback for profiles that predate the
        # explicit gateway_alias key, but only after gateway-specific keys.
        route_values.get("alias"),
        model_values.get("alias"),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return model_id


def _router_spec(configuration: Configuration) -> Mapping[str, Any] | None:
    defaults = _merged_values(configuration.defaults)
    value = defaults.get("router")
    if not isinstance(value, Mapping):
        return None
    return dict(value)


def _router_policy(spec: Mapping[str, Any]) -> RoutingPolicy | None:
    """Build the declarative routing policy configured for a router.

    ``RoutingPolicy`` is intentionally created at the composition boundary.
    The router adapter receives the immutable policy object and is then able
    to filter its prompt catalogue per request (for example, hiding cloud
    candidates unless ``metadata.allow_cloud`` is true).  Keeping this
    conversion here means the policy module never needs to know about YAML or
    application wiring.
    """

    strategy = _merged_values(spec).get("strategy")
    if strategy is None:
        return None
    if isinstance(strategy, RoutingPolicy):
        return strategy
    if not isinstance(strategy, Mapping):
        raise ValueError("defaults.router.strategy must be a mapping")
    return RoutingPolicy.from_mapping(strategy)


def _policy_catalog(policy: RoutingPolicy | None) -> list[Mapping[str, Any]]:
    """Return a JSON-safe candidate catalogue from a parsed policy.

    The policy object exposes immutable ``candidates``/``catalog`` entries;
    this small adapter also accepts mapping-like entries so composition stays
    tolerant of a future policy implementation without embedding model IDs in
    Python.
    """

    if policy is None:
        return []
    values = getattr(policy, "candidates", None)
    if values is None:
        values = getattr(policy, "catalog", ())
    result: list[Mapping[str, Any]] = []
    for candidate in values or ():
        if isinstance(candidate, Mapping):
            result.append(candidate)
            continue
        serialise = getattr(candidate, "to_dict", None)
        if callable(serialise):
            value = serialise()
            if isinstance(value, Mapping):
                result.append(value)
                continue
        value = getattr(candidate, "__dict__", None)
        if isinstance(value, Mapping):
            result.append(value)
    return result


def _merge_router_allow_list(
    configured: Sequence[str] | None,
    policy_catalog: Sequence[Mapping[str, Any]],
    key: str,
) -> Sequence[str] | None:
    """Merge configured and strategy IDs while preserving declaration order."""

    if configured is not None and isinstance(configured, (str, bytes)):
        # Preserve GemmaRouterProvider's strict validation/error wording.
        return configured
    names: list[str] = []
    if configured is not None:
        names.extend(configured)
    for candidate in policy_catalog:
        value = candidate.get(key)
        if isinstance(value, str) and value.strip():
            names.append(value.strip())
    if configured is None and not names:
        return None
    deduped: list[str] = []
    for value in names:
        if value not in deduped:
            deduped.append(value)
    return deduped


def _routing_client(
    configuration: Configuration,
    provider_registry: Any,
    provider_values: Mapping[str, Mapping[str, Any]],
    provider_instances: Mapping[str, Any] | None,
    spec: Mapping[str, Any],
) -> tuple[Any, str, str | None]:
    """Build the local routing-model client used only by GemmaRouterProvider."""

    values = _merged_values(spec)
    routing_model = None
    for key in ("routing_model", "model", "model_id", "routing_model_id"):
        candidate = values.get(key)
        if isinstance(candidate, str) and candidate.strip():
            routing_model = candidate.strip()
            break
    if routing_model is None:
        routing_model = str(values.get("routing_model_name", "")).strip() or None

    routing_provider = None
    for key in ("routing_provider", "provider", "provider_id"):
        candidate = values.get(key)
        if isinstance(candidate, str) and candidate.strip():
            routing_provider = candidate.strip()
            break

    # A router model's provider is the natural fallback when the defaults
    # block only names the model.  Its alias (when present) is the actual model
    # string sent to the local OpenAI-compatible endpoint.
    model_resource = configuration.models.get(routing_model) if routing_model else None
    if model_resource is None and routing_model:
        for candidate_id, candidate in configuration.models.items():
            candidate_values = _merged_values(candidate)
            if routing_model in {candidate_id, candidate_values.get("id"), candidate_values.get("alias")}:
                model_resource = candidate
                if routing_provider is None:
                    routing_provider = str(candidate_values.get("provider") or "") or None
                break
    if model_resource is not None:
        model_values = _merged_values(model_resource)
        if routing_provider is None:
            candidate = model_values.get("provider")
            if isinstance(candidate, str) and candidate.strip():
                routing_provider = candidate.strip()
        if routing_model is None:
            for key in ("routing_model", "alias", "gateway_alias", "id"):
                candidate = model_values.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    routing_model = candidate.strip()
                    break
    if routing_provider is None:
        candidate = values.get("local_provider")
        if isinstance(candidate, str) and candidate.strip():
            routing_provider = candidate.strip()
    if routing_provider is None:
        raise ValueError("defaults.router requires a routing provider")
    if routing_model is None:
        raise ValueError("defaults.router requires a routing model")

    instances = provider_instances or {}
    client = instances.get(routing_provider)
    if client is None:
        # Accept the profile key (``gemma_router``) as a convenience when an
        # injected fake uses the YAML key instead of its canonical provider ID.
        short_name = routing_provider.removeprefix("provider.")
        client = instances.get(short_name)
    if client is not None:
        return client, routing_model, routing_provider

    config = dict(provider_values.get(routing_provider, {}))
    if not config:
        provider = configuration.providers.get(routing_provider)
        config = _merged_values(provider)
    config.setdefault("id", routing_provider)
    config.setdefault("provider_id", routing_provider)
    endpoint = values.get("endpoint") or values.get("base_url") or values.get("url")
    if isinstance(endpoint, str) and endpoint.strip():
        # Explicit router endpoint wins over the provider's generic endpoint.
        config["base_url"] = endpoint.strip()
    config.setdefault("model", routing_model)
    provider_type = config.get("type", config.get("driver", "openai_compatible"))
    creator = getattr(provider_registry, "create", None) or getattr(provider_registry, "build", None)
    if not callable(creator):
        raise TypeError("provider registry has no create/build method for router client")
    client = creator(provider_type, config)
    return client, routing_model, routing_provider


def _build_gemma_router(
    configuration: Configuration,
    provider_registry: Any,
    provider_values: Mapping[str, Mapping[str, Any]],
    provider_instances: Mapping[str, Any] | None,
    spec: Mapping[str, Any],
) -> GemmaRouterProvider:
    client, routing_model, routing_provider = _routing_client(
        configuration,
        provider_registry,
        provider_values,
        provider_instances,
        spec,
    )
    values = _merged_values(spec)
    policy = _router_policy(spec)
    policy_catalog = _policy_catalog(policy)
    # Keep the adapter's global schema constraints broad enough for every
    # declarative strategy candidate.  Request-time policy filtering is still
    # performed by GemmaRouterProvider through ``candidate_catalog``; adding a
    # cloud candidate here does not make it eligible for an ordinary request.
    allowed_models = _merge_router_allow_list(
        values.get("allowed_models"), policy_catalog, "model"
    )
    if allowed_models is None:
        aliases: list[str] = []
        for route in configuration.routes.values():
            if _is_gateway_provider(configuration, route.provider, spec):
                alias = _gateway_model_alias(configuration, route.model, route.provider, route, spec)
                if alias not in aliases:
                    aliases.append(alias)
        allowed_models = aliases or None
    allowed_providers = _merge_router_allow_list(
        values.get("allowed_providers"), policy_catalog, "provider"
    )
    if allowed_providers is None:
        gateway_id = _gateway_provider_id(configuration, spec)
        allowed_providers = [gateway_id] if gateway_id else None

    # GemmaRouterProvider intentionally receives only the local routing client;
    # the selected gateway provider is resolved later by CoreFacade.  No user
    # request is issued while this object is constructed.
    kwargs: dict[str, Any] = {
        "client": client,
        "model": routing_model,
        "provider": routing_provider,
        "allowed_models": allowed_models,
        "allowed_providers": allowed_providers,
        "temperature": values.get("temperature", 0.0),
    }
    if policy is not None:
        kwargs["decision_policy"] = policy
    system_prompt = values.get("system_prompt")
    if isinstance(system_prompt, str) and system_prompt.strip():
        kwargs["system_prompt"] = system_prompt
    return GemmaRouterProvider(**kwargs)


def _build_router(
    configuration: Configuration,
    *,
    provider_registry: Any = None,
    provider_values: Mapping[str, Mapping[str, Any]] | None = None,
    provider_instances: Mapping[str, Any] | None = None,
) -> Any:
    """Build the configured router, retaining StaticRouter compatibility."""

    spec = _router_spec(configuration)
    router_type = str(_merged_values(spec).get("type", "")).lower() if spec else ""
    if spec is not None and router_type in {"gemma", "gemma_router", "gemma-router"}:
        registry = provider_registry or create_default_registry()
        values = provider_values or _provider_values(configuration)
        return _build_gemma_router(configuration, registry, values, provider_instances, spec)

    # No router block (the legacy/default contract) remains a pure static
    # router.  Existing callers and tests can continue to inject their own
    # router object through build_application(..., router=...).

    routes: dict[str, RouteDecision] = {}
    local_providers: set[str] = set()
    cloud_providers: set[str] = set()
    for provider_id, provider in configuration.providers.items():
        if getattr(provider, "kind", "local") == "cloud":
            cloud_providers.add(provider_id)
        else:
            local_providers.add(provider_id)

    def decision(model: str, provider: str, *, reason: str = "configured route") -> RouteDecision:
        return RouteDecision(model=model, provider=provider, reason=reason)

    default: RouteDecision | None = None
    for route_id, route in configuration.routes.items():
        routed_model = _gateway_model_alias(configuration, route.model, route.provider, route, spec)
        item = decision(routed_model, route.provider, reason=f"route {route_id}")
        # Route IDs and model IDs are both useful lookup keys.  The model key
        # is what ``CoreFacade.chat(model_id, ...)`` supplies to the router.
        routes.setdefault(route_id, item)
        routes.setdefault(route.model, item)
        if route_id in {"default", "route.default"}:
            default = item

    if default is None:
        defaults = dict(configuration.defaults or {})
        default_model = defaults.get("model") or defaults.get("default_model")
        default_provider = defaults.get("provider") or defaults.get("default_provider")
        if default_model and default_provider:
            default = decision(
                _gateway_model_alias(configuration, str(default_model), str(default_provider), spec=spec),
                str(default_provider),
                reason="configured default",
            )

    # Legacy files have models but no routes/providers.  A deterministic local
    # route per model preserves existing IDs and keeps cloud fallback disabled.
    for model_id, model in configuration.models.items():
        provider_id = _default_provider_for_model(configuration, model)
        item = decision(
            _gateway_model_alias(configuration, model_id, provider_id, spec=spec),
            provider_id,
            reason="legacy local default",
        )
        routes.setdefault(model_id, item)
        if default is None:
            default = item

    defaults = dict(configuration.defaults or {})
    allow_cloud = bool(defaults.get("allow_cloud_fallback", defaults.get("allow_cloud", False)))
    return StaticRouter(
        routes=routes,
        default=default,
        allow_cloud_fallback=allow_cloud,
        local_providers=local_providers,
        cloud_providers=cloud_providers,
        local_first=True,
    )


@dataclass(slots=True)
class Application:
    """All dependencies created by :func:`build_application`."""

    configuration: Configuration
    registry: Any
    runtime_manager: Any
    manager: Any
    provider_registry: Any
    router: Any
    facade: CoreFacade
    ai_service: AIService

    # Stable aliases for callers that use different terminology.
    @property
    def core(self) -> CoreFacade:
        return self.facade

    @property
    def service(self) -> CoreFacade:
        return self.facade

    @property
    def config(self) -> Configuration:
        return self.configuration

    def close(self) -> Any:
        stop_all = getattr(self.runtime_manager, "stop_all", None)
        if callable(stop_all):
            return stop_all()
        shutdown = getattr(self.runtime_manager, "shutdown", None)
        if callable(shutdown):
            return shutdown()
        return None

    shutdown = close


def build_application(
    config_path: str | Path | None = None,
    *,
    config: str | Path | None = None,
    configuration: Configuration | None = None,
    registry: Any = None,
    runtime_manager: Any = None,
    manager: Any = None,
    provider_registry: Any = None,
    provider_instances: Mapping[str, Any] | None = None,
    router: Any = None,
    facade: CoreFacade | None = None,
    logger: Any = None,
    observability: Any = None,
    auto_start: bool = True,
    runtime_options: Mapping[str, Any] | None = None,
    **runtime_kwargs: Any,
) -> Application:
    """Build the complete local-first application graph.

    All arguments are injectable so tests can provide fakes for the router,
    provider registry, and runtime lifecycle.  No provider request, health
    check, subprocess, or model load is performed during construction.
    """

    if config_path is None and config is not None:
        config_path = config
    loaded = _config_object(config_path, configuration)

    # Keep the old registry's category API while overlaying validated V1 data.
    if registry is None:
        legacy = _legacy_registry(loaded.source_path)
        registry = ApplicationRegistry(loaded, legacy)

    providers = provider_registry or create_default_registry()
    provider_values = _provider_values(loaded)
    provider_values = _provider_values_with_legacy_defaults(loaded, provider_values, providers)

    if router is None:
        router = _build_router(
            loaded,
            provider_registry=providers,
            provider_values=provider_values,
            provider_instances=provider_instances,
        )

    runtime_controller = runtime_manager
    if runtime_controller is None and manager is not None:
        runtime_controller = getattr(manager, "runtime_manager", None)
    if runtime_controller is None:
        options = dict(runtime_options or {})
        options.update(runtime_kwargs)
        runtime_controller = RuntimeManager(**options)

    resource_manager = manager
    if resource_manager is None:
        resource_manager = ResourceManager(registry, runtime_manager=runtime_controller)

    if facade is None:
        facade = CoreFacade(
            manager=resource_manager,
            provider_registry=providers,
            router=router,
            configuration=loaded,
            registry=registry,
            provider_configs=provider_values,
            provider_instances=provider_instances,
            auto_start=auto_start,
            default_model=getattr(getattr(router, "default", None), "model", None),
            default_provider=getattr(getattr(router, "default", None), "provider", None),
            logger=logger,
            observability=observability,
        )

    # ``AIService`` is retained as an explicit compatibility object.  It
    # shares the facade's dependencies but does not construct any provider.
    compatibility = AIService(
        manager=resource_manager,
        router=router,
        provider_registry=providers,
        provider_configs=provider_values,
        provider_instances=provider_instances,
        configuration=loaded,
        registry=registry,
        auto_start=auto_start,
        _suppress_warning=True,
        default_model=getattr(getattr(router, "default", None), "model", None),
        default_provider=getattr(getattr(router, "default", None), "provider", None),
        logger=logger,
        observability=observability,
    )
    return Application(
        configuration=loaded,
        registry=registry,
        runtime_manager=runtime_controller,
        manager=resource_manager,
        provider_registry=providers,
        router=router,
        facade=facade,
        ai_service=compatibility,
    )


create_application = build_application
bootstrap_application = build_application
bootstrap = build_application


__all__ = [
    "Application",
    "ApplicationRegistry",
    "bootstrap",
    "bootstrap_application",
    "build_application",
    "create_application",
]
