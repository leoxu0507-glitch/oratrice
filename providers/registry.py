"""Safe provider registration and construction.

The registry contains an explicit allow-list of provider factories.  It never
imports a module based on configuration text, so a YAML ``type`` cannot cause
arbitrary code execution.  Concrete instances are created only when
``ProviderRegistry.create`` is called; registering a provider is side-effect
free and performs no network/model work.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from providers.base import (
    BaseProvider,
    ProviderConfigurationError,
    ProviderError,
    ProviderProtocol,
)


class UnknownProviderError(ProviderError):
    code = "unknown_provider"


class DuplicateProviderError(ProviderError):
    code = "duplicate_provider"


_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.-]*$")


def _normalise_name(name: str) -> str:
    if not isinstance(name, str):
        raise TypeError("provider name must be a string")
    value = name.strip().lower().replace("-", "_")
    if not value or not _NAME_RE.fullmatch(value) or ".." in value:
        raise ValueError(f"invalid provider name: {name!r}")
    return value


def _config_mapping(config: Any) -> dict[str, Any]:
    if config is None:
        return {}
    if isinstance(config, Mapping):
        return dict(config)
    # ``ProviderConfig`` and similar frozen dataclasses are intentionally
    # accepted without importing core/config modules here.
    values = getattr(config, "__dict__", None)
    if isinstance(values, Mapping):
        return dict(values)
    raise TypeError("provider config must be a mapping or dataclass-like object")


@dataclass(frozen=True, slots=True)
class ProviderRegistration:
    name: str
    factory: Callable[..., Any]
    aliases: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


def _invoke_factory(factory: Callable[..., Any], config: Mapping[str, Any], kwargs: Mapping[str, Any]) -> Any:
    """Invoke a factory without hiding TypeErrors raised by its own body."""

    values = dict(config)
    values.update(kwargs)
    try:
        signature = inspect.signature(factory)
    except (TypeError, ValueError):
        # Builtins may not expose a signature; the positional config convention
        # is the least surprising fallback for registered factories.
        return factory(values)

    parameters = signature.parameters
    accepts_var_kw = any(item.kind == inspect.Parameter.VAR_KEYWORD for item in parameters.values())
    config_parameter = parameters.get("config") or parameters.get("settings")
    if config_parameter is not None and config_parameter.kind in {
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    }:
        call_kwargs = dict(kwargs)
        if config_parameter.kind == inspect.Parameter.KEYWORD_ONLY:
            call_kwargs[config_parameter.name] = values
            return factory(**call_kwargs)
        return factory(values, **kwargs)

    if accepts_var_kw:
        return factory(**values)

    # Prefer keyword construction for classes such as LlamaCppProvider, while
    # retaining a positional one-value convention for simple ``lambda config``
    # fakes used in tests.
    usable = {
        key: value
        for key, value in values.items()
        if key in parameters and parameters[key].kind
        not in {inspect.Parameter.POSITIONAL_ONLY}
    }
    required_positional = [
        item
        for item in parameters.values()
        if item.default is inspect.Parameter.empty
        and item.kind in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
    ]
    if usable or not required_positional:
        return factory(**usable)
    return factory(values)


class ProviderRegistry:
    """Explicit provider factory registry.

    Names and aliases are normalised and unique.  ``register`` accepts a
    class or callable; no instance is constructed until ``create``.  This
    makes registry setup safe to run during configuration loading and easy to
    exercise with offline fakes.
    """

    def __init__(self) -> None:
        self._registrations: dict[str, ProviderRegistration] = {}
        self._aliases: dict[str, str] = {}

    def register(
        self,
        name: str,
        factory: Callable[..., Any],
        *,
        aliases: tuple[str, ...] | list[str] = (),
        metadata: Mapping[str, Any] | None = None,
        replace: bool = False,
    ) -> ProviderRegistration:
        canonical = _normalise_name(name)
        if not callable(factory):
            raise TypeError("provider factory must be callable")
        # Preserve declaration order while collapsing aliases that normalise
        # to the canonical name (e.g. ``llama-cpp`` and ``llama_cpp``).
        alias_names = tuple(
            item
            for item in dict.fromkeys(_normalise_name(value) for value in aliases)
            if item != canonical
        )
        all_names = (canonical, *alias_names)
        occupied = [item for item in all_names if item in self._registrations or item in self._aliases]
        if occupied and not replace:
            raise DuplicateProviderError(
                f"provider name already registered: {occupied[0]}",
                provider=canonical,
            )
        if replace:
            for item in occupied:
                old = self._aliases.pop(item, None)
                if old is not None:
                    self._registrations.pop(old, None)
                self._registrations.pop(item, None)
        registration = ProviderRegistration(
            name=canonical,
            factory=factory,
            aliases=alias_names,
            metadata=dict(metadata or {}),
        )
        self._registrations[canonical] = registration
        for alias in alias_names:
            self._aliases[alias] = canonical
        return registration

    def unregister(self, name: str) -> bool:
        canonical = self._canonical(name)
        if canonical not in self._registrations:
            return False
        registration = self._registrations.pop(canonical)
        for alias in registration.aliases:
            self._aliases.pop(alias, None)
        return True

    def _canonical(self, name: str) -> str:
        normalised = _normalise_name(name)
        return self._aliases.get(normalised, normalised)

    def get(self, name: str) -> ProviderRegistration:
        canonical = self._canonical(name)
        try:
            return self._registrations[canonical]
        except KeyError as exc:
            raise UnknownProviderError(
                f"provider is not registered: {name}",
                provider=name,
            ) from exc

    def has(self, name: str) -> bool:
        try:
            return self._canonical(name) in self._registrations
        except (TypeError, ValueError):
            return False

    # Familiar aliases make the registry convenient for composition roots.
    contains = has

    def names(self, *, include_aliases: bool = False) -> tuple[str, ...]:
        names = list(self._registrations)
        if include_aliases:
            names.extend(self._aliases)
        return tuple(names)

    def registrations(self) -> tuple[ProviderRegistration, ...]:
        return tuple(self._registrations.values())

    def create(
        self,
        name: str | Mapping[str, Any] | Any,
        config: Mapping[str, Any] | Any | None = None,
        **kwargs: Any,
    ) -> Any:
        # Configuration-first construction is useful at a composition root:
        # ``registry.create({"type": "llama_cpp", "base_url": ...})``.  The
        # explicit name form remains preferred when route data already chose a
        # provider.
        if not isinstance(name, str):
            if config is not None:
                raise TypeError("config must be omitted when passed as the provider argument")
            config = name
            values = _config_mapping(config)
            name = values.pop("driver", values.pop("type", values.pop("kind", None)))
            if not isinstance(name, str):
                raise ProviderConfigurationError(
                    "provider config requires a type or driver",
                )
        registration = self.get(name)
        values = _config_mapping(config)
        # ProviderConfig uses ``id`` and ``endpoint`` in a few legacy files;
        # adapters consistently receive the neutral names below.
        if "provider_id" not in values and "id" in values:
            values["provider_id"] = values["id"]
        if "base_url" not in values and "endpoint" in values:
            values["base_url"] = values["endpoint"]
        try:
            instance = _invoke_factory(registration.factory, values, kwargs)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderConfigurationError(
                f"failed to construct provider {name!r}: {exc}",
                provider=registration.name,
                cause=exc,
            ) from exc
        self._validate_instance(instance, registration.name)
        return instance

    # ``build``/``get_instance`` are intentionally aliases, not separate paths.
    build = create
    get_instance = create

    @staticmethod
    def _validate_instance(instance: Any, name: str) -> None:
        required = ("chat", "stream", "health", "models")
        missing = [method for method in required if not callable(getattr(instance, method, None))]
        if missing:
            raise ProviderConfigurationError(
                f"provider factory {name!r} returned an object missing: {', '.join(missing)}",
                provider=name,
            )

    def factory(self) -> "ProviderFactory":
        return ProviderFactory(self)

    resolve = get
    register_provider = register
    list = names


class ProviderFactory:
    """Small composition-root helper around :class:`ProviderRegistry`."""

    def __init__(self, registry: ProviderRegistry | None = None) -> None:
        self.registry = registry or create_default_registry()

    def create(self, provider_type: str | Mapping[str, Any] | Any, config: Mapping[str, Any] | Any | None = None, **kwargs: Any) -> Any:
        return self.registry.create(provider_type, config, **kwargs)

    build = create
    __call__ = create


def create_default_registry() -> ProviderRegistry:
    """Create a fresh registry containing only built-in safe adapters."""

    # Import locally so importing ``providers.registry`` never instantiates an
    # adapter or creates a network client as a module side effect.
    from providers.llama_cpp import LlamaCppProvider
    from providers.litellm_gateway import LiteLLMGatewayProvider

    registry = ProviderRegistry()
    registry.register(
        "llama_cpp",
        LlamaCppProvider,
        aliases=("llama.cpp", "llama-cpp", "openai_compatible", "openai-compatible"),
        metadata={"kind": "local", "protocol": "openai-compatible"},
    )
    # LiteLLM is an explicit, built-in adapter rather than a dynamically
    # imported provider type.  Keeping this registration next to the local
    # llama.cpp adapter makes configuration-driven composition safe: a YAML
    # ``type: litellm_gateway`` can only select this known factory and no
    # provider module is imported from user-controlled text.
    registry.register(
        "litellm_gateway",
        LiteLLMGatewayProvider,
        aliases=("litellm", "lite_llm", "lite-llm", "gateway"),
        metadata={"kind": "local", "protocol": "openai-compatible", "gateway": True},
    )
    return registry


def create_provider(
    provider_type: str,
    config: Mapping[str, Any] | Any | None = None,
    *,
    registry: ProviderRegistry | None = None,
    **kwargs: Any,
) -> Any:
    """Convenience factory that uses an explicit fresh/default registry."""

    return ProviderFactory(registry).create(provider_type, config, **kwargs)


__all__ = [
    "DuplicateProviderError",
    "ProviderFactory",
    "ProviderRegistration",
    "ProviderRegistry",
    "UnknownProviderError",
    "create_default_registry",
    "create_provider",
]
