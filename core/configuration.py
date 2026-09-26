"""Validated configuration contract for Oratrice.

The configuration loader deliberately has no network or process side effects.  It
only parses YAML, expands environment references, normalises paths, and checks
the references between models, runtimes, providers, routes, and policies.

``config/resources.yaml`` (the pre-contract registry format) is still accepted
through :meth:`ConfigurationLoader.load`; this keeps existing callers useful
while new code can use the explicit top-level sections documented in
``config/schema.yaml``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import copy
import os
from pathlib import Path
import re
from typing import Any, Mapping, MutableMapping

import yaml


class ConfigurationError(ValueError):
    """Raised when a configuration file is missing, malformed, or inconsistent."""


_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "access_key",
    "accesskey",
    "secret",
    "token",
    "password",
    "credential",
    "private_key",
)
_PATH_KEY_PARTS = (
    "path",
    "working_dir",
    "workdir",
    "executable",
    "file",
    "directory",
    "dir",
)


def _error(message: str, *, source: Path | None = None) -> ConfigurationError:
    prefix = f"{source}: " if source is not None else ""
    return ConfigurationError(prefix + message)


def _require_mapping(value: Any, label: str, *, source: Path | None = None) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _error(f"{label} must be a mapping", source=source)
    return value


def _validate_id(value: Any, label: str, *, source: Path | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(f"{label} must be a non-empty string", source=source)
    value = value.strip()
    if not _ID_PATTERN.fullmatch(value):
        raise _error(
            f"{label} contains unsupported characters: {value!r}", source=source
        )
    return value


def _expand_env(value: str, *, source: Path) -> str:
    """Expand ``${NAME}`` references and fail closed for missing variables."""

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in os.environ:
            raise _error(
                f"environment variable {name!r} referenced by configuration is not set",
                source=source,
            )
        return os.environ[name]

    return _ENV_PATTERN.sub(replace, value)


def _contains_env_reference(value: str) -> bool:
    return _ENV_PATTERN.search(value) is not None


def _is_secret_key(key: str) -> bool:
    normalised = key.lower().replace("-", "_")
    return any(part in normalised for part in _SECRET_KEY_PARTS)


def _validate_secret_references(value: Any, *, source: Path, location: str) -> None:
    """Reject literal credentials while allowing environment references only."""

    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            child_location = f"{location}.{key_text}"
            if _is_secret_key(key_text) and isinstance(child, str):
                if child and not _contains_env_reference(child):
                    raise _error(
                        f"{child_location} must use an environment reference such as "
                        "${SERVICE_API_KEY}; literal secrets are not allowed",
                        source=source,
                    )
            _validate_secret_references(child, source=source, location=child_location)
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _validate_secret_references(
                child, source=source, location=f"{location}[{index}]"
            )


def _expand_values(value: Any, *, source: Path) -> Any:
    if isinstance(value, str):
        return _expand_env(value, source=source)
    if isinstance(value, Mapping):
        return {key: _expand_values(child, source=source) for key, child in value.items()}
    if isinstance(value, list):
        return [_expand_values(child, source=source) for child in value]
    if isinstance(value, tuple):
        return tuple(_expand_values(child, source=source) for child in value)
    return value


def _resolve_path(value: Any, *, source_dir: Path, label: str, source: Path) -> Path | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise _error(f"{label} must be a non-empty path string", source=source)
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = source_dir / path
    # ``resolve(strict=False)`` normalises ``..`` without requiring a file to
    # exist.  This is important for model files and executables on a new host.
    return path.resolve(strict=False)


def _resolve_path_like_metadata(
    value: Any, *, source_dir: Path, source: Path, key: str
) -> Any:
    """Resolve path-looking metadata without changing arbitrary option strings."""

    if isinstance(value, Mapping):
        return {
            child_key: _resolve_path_like_metadata(
                child,
                source_dir=source_dir,
                source=source,
                key=str(child_key),
            )
            for child_key, child in value.items()
        }
    if isinstance(value, list):
        return [
            _resolve_path_like_metadata(
                child, source_dir=source_dir, source=source, key=key
            )
            for child in value
        ]
    if isinstance(value, str):
        normalised = key.lower().replace("-", "_")
        if any(part in normalised for part in _PATH_KEY_PARTS):
            return _resolve_path(value, source_dir=source_dir, label=key, source=source)
    return value


def _entry_metadata(
    entry: Mapping[str, Any], known: set[str], *, source_dir: Path, source: Path
) -> dict[str, Any]:
    metadata = {key: copy.deepcopy(value) for key, value in entry.items() if key not in known}
    return _resolve_path_like_metadata(
        metadata, source_dir=source_dir, source=source, key="metadata"
    )


@dataclass(frozen=True)
class ModelConfig:
    id: str
    name: str
    runtime: str | None = None
    provider: str | None = None
    path: Path | None = None
    enabled: bool = True
    options: Mapping[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        if key == "id":
            return self.id
        if key == "name":
            return self.name
        if key == "runtime":
            return self.runtime
        if key == "provider":
            return self.provider
        if key == "path":
            return self.path
        if key == "enabled":
            return self.enabled
        return self.options.get(key, default)


@dataclass(frozen=True)
class RuntimeConfig:
    id: str
    name: str
    type: str
    executable: Path | None = None
    working_dir: Path | None = None
    args: tuple[str, ...] = ()
    provider: str | None = None
    enabled: bool = True
    options: Mapping[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        if key == "id":
            return self.id
        if key == "name":
            return self.name
        if key == "type":
            return self.type
        if key == "executable":
            return self.executable
        if key == "working_dir":
            return self.working_dir
        if key == "args":
            return list(self.args)
        if key == "provider":
            return self.provider
        if key == "enabled":
            return self.enabled
        return self.options.get(key, default)


@dataclass(frozen=True)
class ProviderConfig:
    id: str
    name: str
    type: str
    kind: str = "local"
    base_url: str | None = None
    api_key: str | None = None
    enabled: bool = True
    options: Mapping[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        if key == "id":
            return self.id
        if key == "name":
            return self.name
        if key == "type":
            return self.type
        if key in {"kind", "scope"}:
            return self.kind
        if key == "base_url":
            return self.base_url
        if key in {"api_key", "token", "secret"}:
            return self.api_key
        if key == "enabled":
            return self.enabled
        return self.options.get(key, default)


@dataclass(frozen=True)
class RouteConfig:
    id: str
    model: str
    provider: str
    policy: str | None = None
    enabled: bool = True
    options: Mapping[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        if key == "id":
            return self.id
        if key == "model":
            return self.model
        if key == "provider":
            return self.provider
        if key == "policy":
            return self.policy
        if key == "enabled":
            return self.enabled
        return self.options.get(key, default)


@dataclass(frozen=True)
class PolicyConfig:
    id: str
    name: str
    require_local: bool = False
    allow_cloud: bool = True
    allowed_providers: tuple[str, ...] = ()
    enabled: bool = True
    options: Mapping[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        if key == "id":
            return self.id
        if key == "name":
            return self.name
        if key == "require_local":
            return self.require_local
        if key == "allow_cloud":
            return self.allow_cloud
        if key == "allowed_providers":
            return list(self.allowed_providers)
        if key == "enabled":
            return self.enabled
        return self.options.get(key, default)


@dataclass(frozen=True)
class Configuration:
    """Immutable, validated configuration and its source path."""

    source_path: Path
    version: int
    models: Mapping[str, ModelConfig] = field(default_factory=dict)
    runtimes: Mapping[str, RuntimeConfig] = field(default_factory=dict)
    providers: Mapping[str, ProviderConfig] = field(default_factory=dict)
    routes: Mapping[str, RouteConfig] = field(default_factory=dict)
    policies: Mapping[str, PolicyConfig] = field(default_factory=dict)
    defaults: Mapping[str, Any] = field(default_factory=dict)
    legacy_resources: Mapping[str, Any] = field(default_factory=dict)

    @property
    def path(self) -> Path:
        """Alias retained for callers that call the source ``path``."""

        return self.source_path

    def get_model(self, model_id: str) -> ModelConfig | None:
        return self.models.get(model_id)

    def get_runtime(self, runtime_id: str) -> RuntimeConfig | None:
        return self.runtimes.get(runtime_id)

    def get_provider(self, provider_id: str) -> ProviderConfig | None:
        return self.providers.get(provider_id)

    def get_route(self, route_id: str) -> RouteConfig | None:
        return self.routes.get(route_id)

    def get_policy(self, policy_id: str) -> PolicyConfig | None:
        return self.policies.get(policy_id)

    def to_dict(self, *, include_secrets: bool = False) -> dict[str, Any]:
        """Return a serialisable view; secrets are omitted by default."""

        def serialise(value: Any) -> Any:
            if isinstance(value, Path):
                return str(value)
            if isinstance(value, Mapping):
                return {str(key): serialise(child) for key, child in value.items()}
            if isinstance(value, (list, tuple)):
                return [serialise(child) for child in value]
            return value

        result: dict[str, Any] = {
            "version": self.version,
            "models": {key: serialise(value.__dict__) for key, value in self.models.items()},
            "runtimes": {key: serialise(value.__dict__) for key, value in self.runtimes.items()},
            "providers": {},
            "routes": {key: serialise(value.__dict__) for key, value in self.routes.items()},
            "policies": {key: serialise(value.__dict__) for key, value in self.policies.items()},
            "defaults": serialise(self.defaults),
        }
        for key, provider in self.providers.items():
            provider_data = dict(provider.__dict__)
            if not include_secrets:
                provider_data.pop("api_key", None)
            result["providers"][key] = serialise(provider_data)
        if self.legacy_resources:
            result["legacy_resources"] = serialise(self.legacy_resources)
        return result


def _entry_map(raw: Any, section: str, *, source: Path) -> Mapping[str, Mapping[str, Any]]:
    mapping = _require_mapping(raw or {}, section, source=source)
    result: dict[str, Mapping[str, Any]] = {}
    for key, value in mapping.items():
        key_text = _validate_id(str(key), f"{section} entry id", source=source)
        result[key_text] = _require_mapping(
            value, f"{section}.{key_text}", source=source
        )
    return result


def _bool(value: Any, label: str, *, default: bool, source: Path) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise _error(f"{label} must be a boolean", source=source)
    return value


def _text(value: Any, label: str, *, default: str | None, source: Path) -> str | None:
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise _error(f"{label} must be a non-empty string", source=source)
    return value.strip()


def _list_of_text(value: Any, label: str, *, source: Path) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise _error(f"{label} must be a list of strings", source=source)
    result: list[str] = []
    for index, child in enumerate(value):
        if not isinstance(child, str):
            raise _error(f"{label}[{index}] must be a string", source=source)
        result.append(child)
    return tuple(result)


def _parse_new_config(raw: Mapping[str, Any], *, source: Path) -> Configuration:
    allowed_top_level = {
        "version",
        "schema_version",
        "models",
        "runtimes",
        "providers",
        "routes",
        "policies",
        "defaults",
        "metadata",
    }
    unknown = set(raw) - allowed_top_level
    if unknown:
        raise _error(
            "unknown top-level configuration keys: " + ", ".join(sorted(map(str, unknown))),
            source=source,
        )
    version = raw.get("version", raw.get("schema_version", 1))
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise _error("version must be a positive integer", source=source)
    source_dir = source.parent

    raw_models = _entry_map(raw.get("models", {}), "models", source=source)
    raw_runtimes = _entry_map(raw.get("runtimes", {}), "runtimes", source=source)
    raw_providers = _entry_map(raw.get("providers", {}), "providers", source=source)
    raw_routes = _entry_map(raw.get("routes", {}), "routes", source=source)
    raw_policies = _entry_map(raw.get("policies", {}), "policies", source=source)

    models: dict[str, ModelConfig] = {}
    for key, entry in raw_models.items():
        item_id = _validate_id(entry.get("id", key), f"models.{key}.id", source=source)
        name = _text(entry.get("name"), f"models.{key}.name", default=key, source=source)
        runtime = _text(entry.get("runtime"), f"models.{key}.runtime", default=None, source=source)
        provider = _text(entry.get("provider"), f"models.{key}.provider", default=None, source=source)
        path = _resolve_path(entry.get("path"), source_dir=source_dir, label=f"models.{key}.path", source=source)
        enabled = _bool(entry.get("enabled"), f"models.{key}.enabled", default=True, source=source)
        known = {"id", "name", "runtime", "provider", "path", "enabled"}
        models[item_id] = ModelConfig(
            id=item_id,
            name=name or key,
            runtime=runtime,
            provider=provider,
            path=path,
            enabled=enabled,
            options=_entry_metadata(entry, known, source_dir=source_dir, source=source),
        )

    runtimes: dict[str, RuntimeConfig] = {}
    for key, entry in raw_runtimes.items():
        item_id = _validate_id(entry.get("id", key), f"runtimes.{key}.id", source=source)
        name = _text(entry.get("name"), f"runtimes.{key}.name", default=key, source=source)
        runtime_type = _text(entry.get("type"), f"runtimes.{key}.type", default="executable", source=source)
        executable = _resolve_path(entry.get("executable"), source_dir=source_dir, label=f"runtimes.{key}.executable", source=source)
        working_dir = _resolve_path(entry.get("working_dir"), source_dir=source_dir, label=f"runtimes.{key}.working_dir", source=source)
        args_value = entry.get("args", [])
        if not isinstance(args_value, (list, tuple)) or any(not isinstance(arg, str) for arg in args_value):
            raise _error(f"runtimes.{key}.args must be a list of strings", source=source)
        provider = _text(entry.get("provider"), f"runtimes.{key}.provider", default=None, source=source)
        enabled = _bool(entry.get("enabled"), f"runtimes.{key}.enabled", default=True, source=source)
        known = {"id", "name", "type", "executable", "working_dir", "args", "provider", "enabled"}
        runtimes[item_id] = RuntimeConfig(
            id=item_id,
            name=name or key,
            type=runtime_type or "executable",
            executable=executable,
            working_dir=working_dir,
            args=tuple(args_value),
            provider=provider,
            enabled=enabled,
            options=_entry_metadata(entry, known, source_dir=source_dir, source=source),
        )

    providers: dict[str, ProviderConfig] = {}
    for key, entry in raw_providers.items():
        item_id = _validate_id(entry.get("id", key), f"providers.{key}.id", source=source)
        name = _text(entry.get("name"), f"providers.{key}.name", default=key, source=source)
        provider_type = _text(entry.get("type"), f"providers.{key}.type", default="openai_compatible", source=source)
        kind = _text(entry.get("kind", entry.get("scope")), f"providers.{key}.kind", default="local", source=source)
        if kind not in {"local", "cloud"}:
            raise _error(f"providers.{key}.kind must be 'local' or 'cloud'", source=source)
        base_url = _text(entry.get("base_url"), f"providers.{key}.base_url", default=None, source=source)
        api_key = _text(entry.get("api_key", entry.get("token", entry.get("secret"))), f"providers.{key}.api_key", default=None, source=source)
        enabled = _bool(entry.get("enabled"), f"providers.{key}.enabled", default=True, source=source)
        known = {"id", "name", "type", "kind", "scope", "base_url", "api_key", "token", "secret", "enabled"}
        providers[item_id] = ProviderConfig(
            id=item_id,
            name=name or key,
            type=provider_type or "openai_compatible",
            kind=kind or "local",
            base_url=base_url,
            api_key=api_key,
            enabled=enabled,
            options=_entry_metadata(entry, known, source_dir=source_dir, source=source),
        )

    routes: dict[str, RouteConfig] = {}
    for key, entry in raw_routes.items():
        item_id = _validate_id(entry.get("id", key), f"routes.{key}.id", source=source)
        name = item_id  # kept out of the contract; IDs are the stable route names.
        model = _text(entry.get("model"), f"routes.{key}.model", default=None, source=source)
        provider = _text(entry.get("provider"), f"routes.{key}.provider", default=None, source=source)
        if model is None or provider is None:
            raise _error(f"routes.{key} requires model and provider", source=source)
        policy = _text(entry.get("policy"), f"routes.{key}.policy", default=None, source=source)
        enabled = _bool(entry.get("enabled"), f"routes.{key}.enabled", default=True, source=source)
        known = {"id", "model", "provider", "policy", "enabled"}
        routes[item_id] = RouteConfig(
            id=item_id,
            model=model,
            provider=provider,
            policy=policy,
            enabled=enabled,
            options=_entry_metadata(entry, known, source_dir=source_dir, source=source),
        )

    policies: dict[str, PolicyConfig] = {}
    for key, entry in raw_policies.items():
        item_id = _validate_id(entry.get("id", key), f"policies.{key}.id", source=source)
        name = _text(entry.get("name"), f"policies.{key}.name", default=key, source=source)
        require_local = _bool(entry.get("require_local"), f"policies.{key}.require_local", default=False, source=source)
        allow_cloud = _bool(entry.get("allow_cloud"), f"policies.{key}.allow_cloud", default=True, source=source)
        allowed_providers = _list_of_text(entry.get("allowed_providers"), f"policies.{key}.allowed_providers", source=source)
        enabled = _bool(entry.get("enabled"), f"policies.{key}.enabled", default=True, source=source)
        known = {"id", "name", "require_local", "allow_cloud", "allowed_providers", "enabled"}
        policies[item_id] = PolicyConfig(
            id=item_id,
            name=name or key,
            require_local=require_local,
            allow_cloud=allow_cloud,
            allowed_providers=allowed_providers,
            enabled=enabled,
            options=_entry_metadata(entry, known, source_dir=source_dir, source=source),
        )

    # IDs in the YAML key and in the entry are both accepted, but references
    # always use the canonical entry ID.  Build aliases only when unambiguous.
    def ids(mapping: Mapping[str, Any]) -> set[str]:
        return set(mapping) | {item.id for item in mapping.values()}

    model_ids, runtime_ids, provider_ids, route_ids, policy_ids = (
        ids(models), ids(runtimes), ids(providers), ids(routes), ids(policies)
    )
    for model in models.values():
        if model.runtime is not None and model.runtime not in runtime_ids:
            raise _error(f"model {model.id} references unknown runtime {model.runtime!r}", source=source)
        if model.provider is not None and model.provider not in provider_ids:
            raise _error(f"model {model.id} references unknown provider {model.provider!r}", source=source)
    for runtime in runtimes.values():
        if runtime.provider is not None and runtime.provider not in provider_ids:
            raise _error(f"runtime {runtime.id} references unknown provider {runtime.provider!r}", source=source)
    for route in routes.values():
        if route.model not in model_ids:
            raise _error(f"route {route.id} references unknown model {route.model!r}", source=source)
        if route.provider not in provider_ids:
            raise _error(f"route {route.id} references unknown provider {route.provider!r}", source=source)
        if route.policy is not None and route.policy not in policy_ids:
            raise _error(f"route {route.id} references unknown policy {route.policy!r}", source=source)
        policy = policies.get(route.policy) if route.policy else None
        provider = providers.get(route.provider)
        if policy and provider:
            if policy.require_local and provider.kind != "local":
                raise _error(f"route {route.id} violates policy {policy.id}: cloud provider is not allowed", source=source)
            if not policy.allow_cloud and provider.kind == "cloud":
                raise _error(f"route {route.id} violates policy {policy.id}: cloud provider is not allowed", source=source)
            if policy.allowed_providers and route.provider not in policy.allowed_providers:
                raise _error(f"route {route.id} provider {route.provider!r} is not in policy {policy.id}.allowed_providers", source=source)
    for policy in policies.values():
        for provider_id in policy.allowed_providers:
            if provider_id not in provider_ids:
                raise _error(f"policy {policy.id} references unknown provider {provider_id!r}", source=source)

    defaults = _expand_values(raw.get("defaults", {}), source=source)
    if not isinstance(defaults, Mapping):
        raise _error("defaults must be a mapping", source=source)
    defaults = _resolve_path_like_metadata(defaults, source_dir=source_dir, source=source, key="defaults")
    return Configuration(
        source_path=source,
        version=version,
        models=models,
        runtimes=runtimes,
        providers=providers,
        routes=routes,
        policies=policies,
        defaults=defaults,
    )


def _legacy_config(raw_resources: Mapping[str, Any], *, source: Path) -> Configuration:
    """Translate the old ``resources:`` registry without changing its meaning."""

    source_dir = source.parent
    runtimes_raw = _entry_map(raw_resources.get("runtimes", {}), "resources.runtimes", source=source)
    models_raw = _entry_map(raw_resources.get("models", {}), "resources.models", source=source)
    runtimes: dict[str, RuntimeConfig] = {}
    for key, entry in runtimes_raw.items():
        item_id = _validate_id(entry.get("id", key), f"resources.runtimes.{key}.id", source=source)
        runtimes[item_id] = RuntimeConfig(
            id=item_id,
            name=str(entry.get("name", key)),
            type=str(entry.get("type", "executable")),
            executable=_resolve_path(entry.get("executable"), source_dir=source_dir, label=f"resources.runtimes.{key}.executable", source=source),
            working_dir=_resolve_path(entry.get("working_dir"), source_dir=source_dir, label=f"resources.runtimes.{key}.working_dir", source=source),
            args=tuple(entry.get("args", [])),
            provider=entry.get("provider"),
            enabled=bool(entry.get("enabled", True)),
            options=_entry_metadata(entry, {"id", "name", "type", "executable", "working_dir", "args", "provider", "enabled"}, source_dir=source_dir, source=source),
        )
    models: dict[str, ModelConfig] = {}
    for key, entry in models_raw.items():
        item_id = _validate_id(entry.get("id", key), f"resources.models.{key}.id", source=source)
        models[item_id] = ModelConfig(
            id=item_id,
            name=str(entry.get("name", key)),
            runtime=entry.get("runtime"),
            provider=entry.get("provider"),
            path=_resolve_path(entry.get("path"), source_dir=source_dir, label=f"resources.models.{key}.path", source=source),
            enabled=bool(entry.get("enabled", True)),
            options=_entry_metadata(entry, {"id", "name", "runtime", "provider", "path", "enabled"}, source_dir=source_dir, source=source),
        )
    # Legacy files have no provider/route/policy sections.  Keep all untouched
    # categories available to callers instead of silently dropping them.
    legacy = {key: copy.deepcopy(value) for key, value in raw_resources.items() if key not in {"models", "runtimes"}}
    return Configuration(
        source_path=source,
        version=0,
        models=models,
        runtimes=runtimes,
        legacy_resources=legacy,
    )


class ConfigurationLoader:
    """Load and validate a contract YAML file without side effects."""

    def __init__(self, config_path: str | Path | None = None):
        self.config_path = Path(config_path) if config_path is not None else None

    def load(self, config_path: str | Path | None = None) -> Configuration:
        path_value = config_path if config_path is not None else self.config_path
        if path_value is None:
            raise ConfigurationError("a configuration path is required")
        source = Path(path_value).expanduser().resolve(strict=False)
        if not source.exists():
            raise _error("configuration file not found", source=source)
        try:
            with source.open("r", encoding="utf-8") as stream:
                raw = yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            raise _error(f"invalid YAML: {exc}", source=source) from exc
        if raw is None:
            raw = {}
        raw = _require_mapping(raw, "configuration root", source=source)
        _validate_secret_references(raw, source=source, location="config")
        raw = _expand_values(raw, source=source)
        if "resources" in raw:
            if len(raw) != 1:
                raise _error("legacy resources configuration cannot be mixed with new sections", source=source)
            return _legacy_config(_require_mapping(raw["resources"], "resources", source=source), source=source)
        return _parse_new_config(raw, source=source)


ConfigLoader = ConfigurationLoader


def load_configuration(config_path: str | Path) -> Configuration:
    return ConfigurationLoader(config_path).load()


def load_config(config_path: str | Path) -> Configuration:
    """Short alias for :func:`load_configuration`."""

    return load_configuration(config_path)


__all__ = [
    "ConfigLoader",
    "Configuration",
    "ConfigurationError",
    "ConfigurationLoader",
    "ModelConfig",
    "PolicyConfig",
    "ProviderConfig",
    "RouteConfig",
    "RuntimeConfig",
    "load_config",
    "load_configuration",
]
