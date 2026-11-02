"""Offline launcher and configuration self-checks.

The doctor is deliberately a *static* check.  It parses the selected profile,
builds the immutable launch plan, and inspects paths and import metadata.  It
does not construct an application, start a process, open a socket, probe an
endpoint, or load a model.  A requested ``--probe`` is reported as disabled so
that callers never accidentally turn a self-check into a live check.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


STATUS_PASS = "PASS"
STATUS_WARN = "WARN"
STATUS_FAIL = "FAIL"
_STATUSES = {STATUS_PASS, STATUS_WARN, STATUS_FAIL}

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_SECRET_ENV_NAME = re.compile(
    r"(?:^|_)(?:SECRET|TOKEN|KEY|API_?KEY|ACCESS_?KEY|MASTER_?KEY|PASSWORD|PASSWD|CREDENTIAL|AUTH)(?:_|$)",
    re.IGNORECASE,
)
_PATH_FIELDS = {
    "path",
    "model_path",
    "main_model",
    "main_model_path",
    "mmproj",
    "mmproj_path",
    "config_path",
    "config_file",
    "executable",
    "executable_override",
    "working_dir",
    "workdir",
    "directory",
    "dir",
    "file",
}
_PATH_ARGUMENTS = {
    "-m",
    "--model",
    "--model-path",
    "--mmproj",
    "--mmproj-path",
    "--config",
    "--config-file",
}

# These are the runtime packages declared by requirements.txt.  ``pytest``
# and ``httpx`` are useful for the offline test suite but are not required to
# launch the application, so their absence is a warning rather than a failure.
_RUNTIME_MODULES: tuple[tuple[str, str], ...] = (
    ("yaml", "PyYAML"),
    ("requests", "requests"),
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
)
_TEST_MODULES: tuple[tuple[str, str], ...] = (
    ("pytest", "pytest"),
    ("httpx", "httpx"),
)


@dataclass(frozen=True)
class DoctorCheck:
    """One redacted, machine-readable doctor result."""

    name: str
    status: str
    message: str

    def __post_init__(self) -> None:
        if self.status not in _STATUSES:
            raise ValueError(f"unknown doctor status {self.status!r}")

    def to_dict(self) -> dict[str, str]:
        # Keep both names used by early M6 callers.  They carry identical,
        # non-sensitive values and make the JSON contract easy to consume.
        return {
            "name": self.name,
            "check": self.name,
            "status": self.status,
            "message": self.message,
        }


@dataclass(frozen=True)
class DoctorReport:
    """Complete doctor report returned by :func:`check`."""

    profile: str
    checks: tuple[DoctorCheck, ...]
    probe_requested: bool = False

    @property
    def status(self) -> str:
        if any(item.status == STATUS_FAIL for item in self.checks):
            return STATUS_FAIL
        if any(item.status == STATUS_WARN for item in self.checks):
            return STATUS_WARN
        return STATUS_PASS

    @property
    def exit_code(self) -> int:
        # WARN is useful information but keeps the offline doctor usable in a
        # fresh checkout where model/runtime binaries have not been installed.
        return 1 if self.status == STATUS_FAIL else 0

    def to_dict(self) -> dict[str, Any]:
        counts = Counter(item.status for item in self.checks)
        return {
            "mode": "offline",
            "offline": True,
            "profile": self.profile,
            "probe_requested": self.probe_requested,
            "probe_performed": False,
            "status": self.status,
            "checks": [item.to_dict() for item in self.checks],
            "summary": {
                "PASS": counts.get(STATUS_PASS, 0),
                "WARN": counts.get(STATUS_WARN, 0),
                "FAIL": counts.get(STATUS_FAIL, 0),
            },
            "exit_code": self.exit_code,
        }


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _merged_values(value: Any) -> dict[str, Any]:
    """Read dataclass-backed Configuration values without importing models."""

    if isinstance(value, Mapping):
        values = dict(value)
    else:
        try:
            values = dict(vars(value))
        except (TypeError, ValueError):
            values = {}
        if not values:
            for key in (
                "id",
                "name",
                "type",
                "kind",
                "runtime",
                "provider",
                "model",
                "policy",
                "path",
                "executable",
                "working_dir",
                "enabled",
            ):
                candidate = getattr(value, key, None)
                if candidate is not None:
                    values[key] = candidate
    options = values.pop("options", None)
    if isinstance(options, Mapping):
        merged = dict(options)
        merged.update(values)
        return merged
    return values


def _field(value: Any, key: str, default: Any = None) -> Any:
    values = _merged_values(value)
    return values.get(key, default)


def _safe_profile(path: Path) -> str:
    # Paths are useful diagnostics and contain no environment values.  Use a
    # stable string even when ``resolve`` cannot access a parent directory.
    try:
        return str(path.expanduser().resolve(strict=False))
    except OSError:
        return str(path)


def _profile_env_names(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return set()
    return set(_ENV_REF.findall(text))


def _is_path_field(key: str) -> bool:
    normalised = key.lower().replace("-", "_")
    return (
        normalised in _PATH_FIELDS
        or normalised.endswith(("_path", "_file", "_directory", "_dir", "_executable"))
    )


def _path_environment_names(raw: Mapping[str, Any] | None) -> set[str]:
    """Find env references used only as filesystem path inputs."""

    names: set[str] = set()

    def references(value: Any) -> set[str]:
        if isinstance(value, str):
            return set(_ENV_REF.findall(value))
        if isinstance(value, Mapping):
            return set().union(*(references(child) for child in value.values())) if value else set()
        if isinstance(value, (list, tuple)):
            return set().union(*(references(child) for child in value)) if value else set()
        return set()

    def argument_references(value: Any, path_arguments: set[str]) -> set[str]:
        if not isinstance(value, (list, tuple)):
            return set()
        result: set[str] = set()
        expects_path = False
        for argument in value:
            if not isinstance(argument, str):
                expects_path = False
                continue
            if expects_path:
                result.update(_ENV_REF.findall(argument))
                expects_path = False
                continue
            if argument in path_arguments:
                expects_path = True
                continue
            if any(argument.startswith(option + "=") for option in path_arguments):
                result.update(_ENV_REF.findall(argument))
        return result

    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            runtime_type = str(value.get("type", "")).lower()
            runtime_path_arguments = set(_PATH_ARGUMENTS)
            if runtime_type == "service":
                runtime_path_arguments.discard("-m")
            for key, child in value.items():
                key_text = str(key)
                if _is_path_field(key_text):
                    names.update(references(child))
                if key_text == "args":
                    names.update(argument_references(child, runtime_path_arguments))
                elif key_text == "runtime_args":
                    # Defaults mirror commands for display; short ``-m`` is
                    # ambiguous there and commonly means a Python module.
                    defaults_path_arguments = runtime_path_arguments - {"-m"}
                    names.update(argument_references(child, defaults_path_arguments))
                elif key_text == "argument_overrides" and isinstance(child, Mapping):
                    for option, override in child.items():
                        if str(option) in runtime_path_arguments:
                            names.update(references(override))
                walk(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                walk(child)

    if raw is not None:
        walk(raw)
    return names


def _raw_profile(path: Path) -> Mapping[str, Any] | None:
    """Read only the raw mapping needed for env/target diagnostics."""

    try:
        import yaml  # type: ignore[import-not-found]

        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return value if isinstance(value, Mapping) else None


def _load_configuration(
    path: Path,
    environ: Mapping[str, str],
    *,
    raw: Mapping[str, Any] | None = None,
) -> tuple[Any | None, Exception | None]:
    """Load a profile with placeholders for missing ``${ENV}`` references.

    ``ConfigurationLoader`` intentionally reads ``os.environ``.  Missing
    values are replaced only for this parse and are restored in a ``finally``
    block; the caller's environment mapping and the process environment are
    never changed permanently, and no value is printed.
    """

    try:
        from core.configuration import ConfigurationLoader
    except Exception as exc:  # pragma: no cover - exercised on broken installs
        return None, exc

    names = _profile_env_names(path)
    path_names = _path_environment_names(raw if raw is not None else _raw_profile(path))
    saved: dict[str, str | None] = {}
    had: set[str] = set()
    try:
        for name in names:
            if name in os.environ:
                had.add(name)
                saved[name] = os.environ[name]
            else:
                saved[name] = None
            # Expand only supplied, non-secret values that the profile uses
            # as paths. Other references stay placeholders so secrets and
            # unrelated environment values never enter the configuration.
            value = environ.get(name)
            if name in path_names and not _SECRET_ENV_NAME.search(name) and isinstance(value, str) and value:
                os.environ[name] = value
            else:
                os.environ[name] = "__oratrice_doctor_placeholder__"
        return ConfigurationLoader(path).load(), None
    except Exception as exc:
        return None, exc
    finally:
        for name, value in saved.items():
            if name in had and value is not None:
                os.environ[name] = value
            else:
                os.environ.pop(name, None)


def _check_profile_path(path: Path) -> DoctorCheck:
    if not path.exists():
        return DoctorCheck("config.path", STATUS_FAIL, "profile file is missing")
    if not path.is_file():
        return DoctorCheck("config.path", STATUS_FAIL, "profile path is not a file")
    try:
        path.read_bytes()
    except OSError:
        return DoctorCheck("config.path", STATUS_FAIL, "profile file is not readable")
    return DoctorCheck("config.path", STATUS_PASS, "profile file is readable")


def _effective_arguments(arguments: Sequence[str], overrides: Mapping[str, str]) -> tuple[str, ...]:
    result = [str(value) for value in arguments]
    for option, value in overrides.items():
        found = False
        index = 0
        while index < len(result):
            if result[index] == option:
                found = True
                if index + 1 < len(result):
                    result[index + 1] = str(value)
                else:
                    result.append(str(value))
                index += 2
            else:
                index += 1
        if not found:
            result.extend((option, str(value)))
    return tuple(result)


def _argument_paths(
    arguments: Sequence[str],
    *,
    runtime: Any,
    configuration: Any,
    runtime_id: str,
) -> list[tuple[str, Path, str]]:
    """Return declared model, projector, and config paths from launch args."""

    working_dir = _field(runtime, "working_dir")
    source_path = getattr(configuration, "source_path", None)
    base = working_dir if isinstance(working_dir, Path) else (
        source_path.parent if isinstance(source_path, Path) else Path.cwd()
    )
    result: list[tuple[str, Path, str]] = []
    path_arguments = set(_PATH_ARGUMENTS)
    if str(_field(runtime, "type", "")).lower() == "service":
        path_arguments.discard("-m")

    def add(option: str, raw_path: str) -> None:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = base / path
        result.append((f"runtimes.{runtime_id}.args[{option}]", path.resolve(strict=False), option))

    index = 0
    while index < len(arguments):
        argument = str(arguments[index])
        option = next((item for item in path_arguments if argument.startswith(item + "=")), None)
        if option is not None:
            add(option, argument.split("=", 1)[1])
        elif argument in path_arguments and index + 1 < len(arguments):
            add(argument, str(arguments[index + 1]))
            index += 1
        index += 1
    return result


def _profile_path_value(configuration: Any, value: Any, label: str) -> Path | None:
    """Read typed paths plus common path aliases left as metadata strings."""

    if isinstance(value, Path):
        return value
    field_name = label.rsplit(".", 1)[-1].split("[", 1)[0]
    if not isinstance(value, str) or not value.strip() or not _is_path_field(field_name):
        return None
    path = Path(value).expanduser()
    source_path = getattr(configuration, "source_path", None)
    if not path.is_absolute():
        base = source_path.parent if isinstance(source_path, Path) else Path.cwd()
        path = base / path
    try:
        return path.resolve(strict=False)
    except OSError:
        return path


def _path_items(configuration: Any, plan: Any | None) -> list[tuple[str, Path, bool, bool]]:
    """Return ``(field label, path, directory expected, required)`` entries."""

    runtimes = getattr(configuration, "runtimes", {})
    models = getattr(configuration, "models", {})
    plan_targets = tuple(getattr(plan, "targets", ())) if plan is not None else ()
    optional_targets = tuple(getattr(plan, "optional_targets", ())) if plan is not None else ()
    targets_by_runtime: dict[str, list[Any]] = {}
    required_runtime_ids: set[str] = set()
    for target in (*plan_targets, *optional_targets):
        runtime_id = str(getattr(target, "runtime_id", ""))
        if runtime_id:
            targets_by_runtime.setdefault(runtime_id, []).append(target)
            if target in plan_targets:
                required_runtime_ids.add(runtime_id)

    result_by_path: dict[tuple[str, bool], tuple[str, Path, bool, bool]] = {}

    def add(label: str, value: Any, *, directory: bool = False, required: bool = False) -> None:
        if not isinstance(value, Path):
            return
        key = (str(value), directory)
        existing = result_by_path.get(key)
        if existing is None:
            result_by_path[key] = (label, value, directory, required)
            return
        old_label, old_path, old_directory, old_required = existing
        # Prefer the resource's field label over a duplicate command argument
        # label, while preserving requiredness from whichever source uses it.
        label_rank = 0 if label.startswith(("models.", "defaults.")) else 1
        old_rank = 0 if old_label.startswith(("models.", "defaults.")) else 1
        preferred_label = label if label_rank < old_rank else old_label
        result_by_path[key] = (preferred_label, old_path, old_directory, old_required or required)

    def walk(value: Any, label: str, *, required: bool) -> None:
        path_value = _profile_path_value(configuration, value, label)
        if path_value is not None:
            directory = label.lower().endswith(("working_dir", "workdir", ".dir", ".directory"))
            add(label, path_value, directory=directory, required=required)
        elif isinstance(value, Mapping):
            for child_key, child in value.items():
                walk(child, f"{label}.{child_key}", required=required)
        elif isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                walk(child, f"{label}[{index}]", required=required)

    # The selected target decides which executable is actually used. A stale
    # runtime executable is not a required asset when every selected target
    # for that runtime supplies an executable override.
    for runtime_id, item in (runtimes.items() if isinstance(runtimes, Mapping) else ()):
        runtime_targets = targets_by_runtime.get(str(runtime_id), [])
        required_targets = [target for target in runtime_targets if target in plan_targets]
        target_uses_runtime_executable = (
            not runtime_targets
            or any(getattr(target, "executable_override", None) is None for target in required_targets)
            or (not required_targets and all(
                getattr(target, "executable_override", None) is None for target in runtime_targets
            ))
        )
        if target_uses_runtime_executable:
            add(
                f"runtimes.{runtime_id}.executable",
                _field(item, "executable"),
                required=bool(required_targets),
            )
        add(
            f"runtimes.{runtime_id}.working_dir",
            _field(item, "working_dir"),
            directory=True,
            required=bool(required_targets),
        )
        options = getattr(item, "options", None)
        if isinstance(options, Mapping):
            walk(options, f"runtimes.{runtime_id}.metadata", required=bool(required_targets))

        arguments = tuple(getattr(item, "args", ()) or ())
        for target in runtime_targets:
            effective = _effective_arguments(
                arguments,
                getattr(target, "argument_overrides", {}) or {},
            )
            for label, path, _option in _argument_paths(
                effective,
                runtime=item,
                configuration=configuration,
                runtime_id=str(runtime_id),
            ):
                add(label, path, required=target in plan_targets)

    argument_model_paths: dict[str, set[Path]] = {}
    argument_mmproj_paths: dict[str, set[Path]] = {}
    for target in plan_targets:
        runtime_id = str(getattr(target, "runtime_id", ""))
        runtime = runtimes.get(runtime_id) if isinstance(runtimes, Mapping) else None
        if runtime is None:
            continue
        effective = _effective_arguments(
            tuple(getattr(runtime, "args", ()) or ()),
            getattr(target, "argument_overrides", {}) or {},
        )
        for _label, path, option in _argument_paths(
            effective,
            runtime=runtime,
            configuration=configuration,
            runtime_id=runtime_id,
        ):
            if option in {"-m", "--model", "--model-path"}:
                argument_model_paths.setdefault(runtime_id, set()).add(path)
            elif option in {"--mmproj", "--mmproj-path"}:
                argument_mmproj_paths.setdefault(runtime_id, set()).add(path)

    for key, item in (models.items() if isinstance(models, Mapping) else ()):
        runtime_id = _field(item, "runtime")
        model_enabled = bool(_field(item, "enabled", True))
        required_runtime = model_enabled and runtime_id in required_runtime_ids
        model_path = _field(item, "path")
        expected_model_paths = argument_model_paths.get(str(runtime_id), set())
        model_path_required = required_runtime and (
            not expected_model_paths or model_path in expected_model_paths
        )
        add(f"models.{key}.path", model_path, required=model_path_required)

        options = getattr(item, "options", None)
        if isinstance(options, Mapping):
            for option_key, option_value in options.items():
                option_label = f"models.{key}.metadata.{option_key}"
                if isinstance(option_value, Path) and "mmproj" in str(option_key).lower():
                    expected_mmproj_paths = argument_mmproj_paths.get(str(runtime_id), set())
                    option_required = required_runtime and (
                        not expected_mmproj_paths or option_value in expected_mmproj_paths
                    )
                    add(option_label, option_value, required=option_required)
                else:
                    walk(option_value, option_label, required=required_runtime)

    # Defaults can carry path-like fields (such as gateway config_path). A
    # containing resource is required only when its runtime/provider/model
    # reference belongs to a selected target.
    required_refs: set[str] = set()
    for target in plan_targets:
        required_refs.update({str(getattr(target, "id", "")), str(getattr(target, "runtime_id", ""))})
        runtime = runtimes.get(str(getattr(target, "runtime_id", ""))) if isinstance(runtimes, Mapping) else None
        provider = _field(runtime, "provider") if runtime is not None else None
        if provider:
            required_refs.add(str(provider))
        for model in (models.values() if isinstance(models, Mapping) else ()):
            if _field(model, "runtime") == getattr(target, "runtime_id", None):
                model_id = _field(model, "id")
                if model_id:
                    required_refs.add(str(model_id))

    def walk_defaults(value: Any, label: str, *, required_context: bool = False) -> None:
        if isinstance(value, Mapping):
            references = {
                str(child)
                for key, child in value.items()
                if str(key).lower() in {"id", "runtime", "runtime_id", "provider", "provider_id", "model", "model_id", "target", "target_id"}
            }
            required_here = required_context or bool(references & required_refs)
            for child_key, child in value.items():
                key_text = str(child_key)
                if label == "defaults" and key_text == "launcher":
                    continue
                walk_defaults(
                    child,
                    f"{label}.{key_text}",
                    required_context=required_here,
                )
        elif isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                walk_defaults(
                    child,
                    f"{label}[{index}]",
                    required_context=required_context,
                )
        else:
            path_value = _profile_path_value(configuration, value, label)
            if path_value is not None:
                directory = label.lower().endswith(("working_dir", "workdir", ".dir", ".directory"))
                add(label, path_value, directory=directory, required=required_context)

    defaults = getattr(configuration, "defaults", {})
    if isinstance(defaults, Mapping):
        walk_defaults(defaults, "defaults")

    if plan is not None:
        for target in (*plan_targets, *optional_targets):
            required = target in plan_targets
            override = getattr(target, "executable_override", None)
            add(f"launcher.{getattr(target, 'id', 'target')}.executable_override", override, required=required)

    return list(result_by_path.values())


def _path_corrections(labels: Sequence[str]) -> str:
    lower_labels = tuple(label.lower() for label in labels)
    actions: list[str] = []
    if any("executable" in label for label in lower_labels):
        actions.append("install the selected runtime or correct its executable field")
    if any("working_dir" in label or "workdir" in label for label in lower_labels):
        actions.append("create the required directory or correct its working_dir field")
    if any("mmproj" in label or label.startswith("models.") for label in lower_labels):
        actions.append("download or restore the model/mmproj asset and correct its labeled model field")
    if any("config" in label for label in lower_labels):
        actions.append("create the required config file or correct its labeled config_path field")
    if not actions:
        actions.append("correct the labeled field or set its non-secret path environment variable")
    return "; next: " + "; ".join(dict.fromkeys(actions)) + "."


def _check_paths(configuration: Any, plan: Any | None, *, strict_paths: bool = False) -> DoctorCheck:
    items = _path_items(configuration, plan)
    missing_required: list[str] = []
    missing_optional: list[str] = []
    wrong_required: list[str] = []
    wrong_optional: list[str] = []
    for label, path, directory, required in items:
        try:
            exists = path.exists()
            valid = path.is_dir() if directory else path.is_file()
        except OSError:
            exists = False
            valid = False
        if not exists:
            (missing_required if required else missing_optional).append(label)
        elif not valid:
            (wrong_required if required else wrong_optional).append(label)

    messages: list[str] = []
    if missing_required:
        messages.append("missing required fields: " + ", ".join(missing_required))
    if missing_optional:
        messages.append("missing inactive/optional fields: " + ", ".join(missing_optional))
    if wrong_required:
        messages.append("wrong type for required fields: " + ", ".join(wrong_required))
    if wrong_optional:
        messages.append("wrong type for inactive/optional fields: " + ", ".join(wrong_optional))
    if messages:
        labels = missing_required + missing_optional + wrong_required + wrong_optional
        messages.append(_path_corrections(labels).lstrip("; "))
        failed = bool(wrong_required) or (strict_paths and bool(missing_required))
        if failed:
            return DoctorCheck("paths", STATUS_FAIL, "; ".join(messages))
        return DoctorCheck("paths", STATUS_WARN, "; ".join(messages))
    return DoctorCheck("paths", STATUS_PASS, f"{len(items)} configured path(s) are present")


def _canonical_index(section: Any, aliases: Sequence[str]) -> tuple[dict[str, set[str]], int]:
    index: dict[str, set[str]] = {}
    count = 0
    if not isinstance(section, Mapping):
        return index, count
    for key, item in section.items():
        canonical = _field(item, "id", key)
        canonical = str(canonical).strip() if canonical is not None else str(key)
        values = {str(key), canonical}
        for alias in aliases:
            value = _field(item, alias)
            if isinstance(value, str) and value.strip():
                values.add(value.strip())
        for value in values:
            index.setdefault(value, set()).add(canonical)
        count += 1
    return index, count


def _resolve(index: Mapping[str, set[str]], value: Any) -> set[str]:
    if not isinstance(value, str) or not value.strip():
        return set()
    return set(index.get(value.strip(), ()))


def _check_aliases(configuration: Any) -> DoctorCheck:
    models = getattr(configuration, "models", {})
    providers = getattr(configuration, "providers", {})
    runtimes = getattr(configuration, "runtimes", {})
    policies = getattr(configuration, "policies", {})
    model_index, model_count = _canonical_index(
        models, ("alias", "gateway_alias", "gateway_model", "model_alias")
    )
    # ``gateway_alias`` identifies a shared transport (the local and cloud
    # LiteLLM providers intentionally both use ``litellm``), so it is not a
    # globally unique provider identity.  Canonical provider references still
    # resolve through each mapping key/id and explicit provider aliases.
    provider_index, provider_count = _canonical_index(
        providers, ("alias", "provider_alias")
    )
    runtime_index, _ = _canonical_index(runtimes, ("alias",))
    policy_index, _ = _canonical_index(policies, ("alias",))
    errors: list[str] = []
    errors.extend(
        f"model alias maps to multiple resources ({len(values)})"
        for values in model_index.values()
        if len(values) > 1
    )
    errors.extend(
        f"provider alias maps to multiple resources ({len(values)})"
        for values in provider_index.values()
        if len(values) > 1
    )

    def require(index: Mapping[str, set[str]], value: Any, label: str) -> None:
        if value is None:
            return
        if not _resolve(index, value):
            errors.append(f"{label} references an unknown canonical alias")

    for key, item in (models.items() if isinstance(models, Mapping) else ()):
        require(runtime_index, _field(item, "runtime"), f"model {key} runtime")
        require(provider_index, _field(item, "provider"), f"model {key} provider")
    for key, item in (runtimes.items() if isinstance(runtimes, Mapping) else ()):
        require(provider_index, _field(item, "provider"), f"runtime {key} provider")
    for key, item in (getattr(configuration, "routes", {}) or {}).items():
        require(model_index, _field(item, "model"), f"route {key} model")
        require(provider_index, _field(item, "provider"), f"route {key} provider")
        require(policy_index, _field(item, "policy"), f"route {key} policy")

    defaults = _mapping(getattr(configuration, "defaults", {}))
    router = _mapping(defaults.get("router"))
    strategy = _mapping(router.get("strategy"))
    candidates = strategy.get("candidates", ())
    if isinstance(candidates, Sequence) and not isinstance(candidates, (str, bytes, bytearray)):
        for index, candidate in enumerate(candidates):
            if not isinstance(candidate, Mapping):
                errors.append(f"router candidate {index} is not a mapping")
                continue
            require(model_index, candidate.get("model"), f"router candidate {index} model")
            require(provider_index, candidate.get("provider"), f"router candidate {index} provider")

    gateway = _mapping(defaults.get("gateway"))
    aliases = gateway.get("model_aliases")
    if isinstance(aliases, Mapping):
        for key, value in aliases.items():
            require(model_index, key, f"gateway model alias {key}")
            require(model_index, value, f"gateway model alias {key} target")

    if errors:
        return DoctorCheck("aliases", STATUS_FAIL, f"{len(errors)} canonical alias/reference issue(s)")
    return DoctorCheck(
        "aliases",
        STATUS_PASS,
        f"canonical aliases resolve ({model_count} model(s), {provider_count} provider(s))",
    )


def _check_dependencies() -> DoctorCheck:
    missing_runtime: list[str] = []
    missing_tests: list[str] = []
    for module, package in _RUNTIME_MODULES:
        try:
            found = importlib.util.find_spec(module) is not None
        except (ImportError, AttributeError, ValueError):
            found = False
        if not found:
            missing_runtime.append(package)
    for module, package in _TEST_MODULES:
        try:
            found = importlib.util.find_spec(module) is not None
        except (ImportError, AttributeError, ValueError):
            found = False
        if not found:
            missing_tests.append(package)
    if missing_runtime:
        return DoctorCheck(
            "dependencies",
            STATUS_FAIL,
            f"runtime module(s) not discoverable: {', '.join(sorted(missing_runtime))}",
        )
    if missing_tests:
        return DoctorCheck(
            "dependencies",
            STATUS_WARN,
            f"runtime modules discoverable; test module(s) missing: {', '.join(sorted(missing_tests))}",
        )
    return DoctorCheck("dependencies", STATUS_PASS, "runtime and test modules are discoverable")


def _required_environment(
    configuration: Any, raw: Mapping[str, Any] | None
) -> dict[str, tuple[bool, bool]]:
    """Return ``name -> (launcher_required, launcher_can_generate)``.

    Raw provider/profile references are useful diagnostics, but are not by
    themselves launch requirements.  This distinction keeps optional cloud
    credentials (for example a DeepSeek key) at WARN while a target's explicit
    ``required_env`` remains FAIL when it cannot be generated.
    """

    required: dict[str, tuple[bool, bool]] = {}
    defaults = _mapping(getattr(configuration, "defaults", {}))
    launcher = _mapping(defaults.get("launcher"))
    targets = launcher.get("targets", ())
    optional = launcher.get("optional_targets", ())
    target_values: list[Any] = []
    if isinstance(targets, Sequence) and not isinstance(targets, (str, bytes, bytearray)):
        target_values.extend(targets)
    if isinstance(optional, Sequence) and not isinstance(optional, (str, bytes, bytearray)):
        target_values.extend(optional)
    for target in target_values:
        if not isinstance(target, Mapping):
            continue
        generated = bool(target.get("generate_if_missing", False))
        names = target.get("required_env", ())
        if isinstance(names, Sequence) and not isinstance(names, (str, bytes, bytearray)):
            for name in names:
                if isinstance(name, str) and name.strip():
                    key = name.strip()
                    _old_required, old_generated = required.get(key, (False, False))
                    required[key] = (True, generated or old_generated)
    # Raw references catch environments used by providers even when a launch
    # target does not repeat ``required_env``.  A generated target remains a
    # warning; any other missing reference is a real configuration failure.
    if raw is not None:
        for name in _ENV_REF.findall(_dump_mapping(raw)):
            required.setdefault(name, (False, False))
    return required


def _dump_mapping(value: Any) -> str:
    """Serialize raw YAML without exposing process environment values."""

    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return repr(value)


def _check_environment(configuration: Any, raw: Mapping[str, Any] | None, environ: Mapping[str, str]) -> DoctorCheck:
    required = _required_environment(configuration, raw)
    def present(name: str) -> bool:
        value = environ.get(name)
        return value is not None and bool(str(value).strip())

    missing_fail = sorted(
        name
        for name, (launcher_required, generated) in required.items()
        if not present(name) and launcher_required and not generated
    )
    missing_warn = sorted(
        name
        for name, (launcher_required, generated) in required.items()
        if not present(name) and (not launcher_required or generated)
    )
    if missing_fail:
        return DoctorCheck(
            "environment",
            STATUS_FAIL,
            f"required environment variable(s) are missing: {', '.join(missing_fail)}",
        )
    if missing_warn:
        return DoctorCheck(
            "environment",
            STATUS_WARN,
            f"environment variable(s) absent; launcher may generate them: {', '.join(missing_warn)}",
        )
    if required:
        return DoctorCheck("environment", STATUS_PASS, f"{len(required)} required environment variable(s) are set")
    return DoctorCheck("environment", STATUS_PASS, "no required environment variables are configured")


def check(
    profile: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
    probe: bool = False,
    strict_paths: bool = False,
) -> DoctorReport:
    """Run the pure offline checks and return a report.

    ``probe`` is intentionally informational.  It never performs a network or
    port check; callers can use it to detect that a future live probe was
    requested while preserving this command's offline contract.
    """

    path = Path(profile).expanduser().resolve(strict=False)
    env = environ if environ is not None else os.environ
    checks: list[DoctorCheck] = [_check_profile_path(path)]
    raw = _raw_profile(path)
    configuration, error = _load_configuration(path, env, raw=raw) if path.is_file() else (None, None)
    if error is not None or configuration is None:
        checks.append(DoctorCheck("config.parse", STATUS_FAIL, "configuration could not be parsed"))
        # Keep the output useful while avoiding an exception string that might
        # contain a credential or a value expanded from one.
        checks.append(_check_environment(configuration, raw, env) if configuration is not None else DoctorCheck("environment", STATUS_WARN, "environment check deferred until configuration parses"))
        checks.append(_check_dependencies())
        if probe:
            checks.append(DoctorCheck("probe", STATUS_WARN, "probe requested but disabled; no network was attempted"))
        return DoctorReport(_safe_profile(path), tuple(checks), probe_requested=probe)

    checks.append(DoctorCheck("config.parse", STATUS_PASS, "configuration parsed and references validated"))

    plan = None
    try:
        from launcher.plan import LaunchPlan

        plan = LaunchPlan.from_configuration(configuration)
    except Exception:
        checks.append(DoctorCheck("launcher.plan", STATUS_FAIL, "launcher target references are invalid"))
    else:
        checks.append(DoctorCheck("launcher.plan", STATUS_PASS, "launcher targets and ordering are valid"))

    checks.append(_check_paths(configuration, plan, strict_paths=strict_paths))
    checks.append(_check_aliases(configuration))
    checks.append(_check_dependencies())
    checks.append(_check_environment(configuration, raw, env))
    if probe:
        checks.append(DoctorCheck("probe", STATUS_WARN, "probe requested but disabled; no network was attempted"))
    return DoctorReport(_safe_profile(path), tuple(checks), probe_requested=probe)


def _print_human(report: DoctorReport, output: Callable[[str], Any]) -> None:
    output("Oratrice doctor (offline; no process/network/model loading)")
    for item in report.checks:
        output(f"{item.status:<4} {item.name}: {item.message}")
    counts = Counter(item.status for item in report.checks)
    output(
        "SUMMARY "
        + " ".join(f"{name}={counts.get(name, 0)}" for name in ("PASS", "WARN", "FAIL"))
        + f" status={report.status} exit={report.exit_code}"
    )


def run_doctor(
    profile: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
    probe: bool = False,
    strict_paths: bool = False,
    json_output: bool = False,
    output: Callable[[str], Any] = print,
) -> int:
    """Run and render the doctor, returning a process-style exit code."""

    report = check(profile, environ=environ, probe=probe, strict_paths=strict_paths)
    if json_output:
        output(json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True))
    else:
        _print_human(report, output)
    return report.exit_code


# Common aliases keep the tiny module convenient for embedders and tests.
run = run_doctor
doctor = check


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - thin CLI shim
    import argparse
    from core.configuration import default_service_profile

    parser = argparse.ArgumentParser(description="Run the offline Oratrice self-check")
    parser.add_argument(
        "--profile",
        default=str(default_service_profile(Path(__file__).resolve().parents[1])),
    )
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--strict-paths", action="store_true")
    args = parser.parse_args(argv)
    return run_doctor(
        args.profile,
        probe=args.probe,
        strict_paths=args.strict_paths,
        json_output=args.json_output,
    )


__all__ = [
    "DoctorCheck",
    "DoctorReport",
    "STATUS_FAIL",
    "STATUS_PASS",
    "STATUS_WARN",
    "check",
    "doctor",
    "main",
    "run",
    "run_doctor",
]
