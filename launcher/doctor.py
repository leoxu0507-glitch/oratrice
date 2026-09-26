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


def _raw_profile(path: Path) -> Mapping[str, Any] | None:
    """Read only the raw mapping needed for env/target diagnostics."""

    try:
        import yaml  # type: ignore[import-not-found]

        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return value if isinstance(value, Mapping) else None


def _load_configuration(path: Path, environ: Mapping[str, str]) -> tuple[Any | None, Exception | None]:
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
    saved: dict[str, str | None] = {}
    had: set[str] = set()
    for name in names:
        if name in os.environ:
            had.add(name)
            saved[name] = os.environ[name]
        else:
            saved[name] = None
        # A placeholder is enough for validation.  In particular, do not copy
        # an injected secret from ``environ`` into process state.
        os.environ[name] = "__oratrice_doctor_placeholder__"
    try:
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


def _path_items(configuration: Any, plan: Any | None) -> list[tuple[str, Path, bool]]:
    """Return ``(label, path, directory_expected)`` without touching files."""

    result: list[tuple[str, Path, bool]] = []
    seen: set[tuple[str, str, bool]] = set()

    def add(label: str, value: Any, *, directory: bool = False) -> None:
        if not isinstance(value, Path):
            return
        key = (label, str(value), directory)
        if key not in seen:
            seen.add(key)
            result.append((label, value, directory))

    def walk(value: Any, label: str) -> None:
        if isinstance(value, Path):
            directory = label.lower().endswith(("working_dir", "workdir", ".dir", ".directory"))
            add(label, value, directory=directory)
        elif isinstance(value, Mapping):
            for child_key, child in value.items():
                walk(child, f"{label}.{child_key}")
        elif isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                walk(child, f"{label}[{index}]")

    for section_name in ("runtimes", "models"):
        section = getattr(configuration, section_name, {})
        if not isinstance(section, Mapping):
            continue
        for key, item in section.items():
            prefix = f"{section_name}.{key}"
            add(f"{prefix}.executable", _field(item, "executable"))
            add(f"{prefix}.working_dir", _field(item, "working_dir"), directory=True)
            add(f"{prefix}.path", _field(item, "path"))

            # Configuration dataclasses merge ``options`` into their public
            # mapping.  Walk the original options when present so metadata
            # paths such as ``mmproj_path`` and ``config_path`` are checked.
            options = getattr(item, "options", None)
            if isinstance(options, Mapping):
                walk(options, f"{prefix}.metadata")

    # Defaults hold launcher and gateway metadata whose path-like keys are
    # normalised by ConfigurationLoader (for example ``gateway.config_path``).
    walk(getattr(configuration, "defaults", {}), "defaults")

    if plan is not None:
        for target in (*getattr(plan, "targets", ()), *getattr(plan, "optional_targets", ())):
            override = getattr(target, "executable_override", None)
            add(f"launcher.{getattr(target, 'id', 'target')}.executable_override", override)
    return result


def _check_paths(configuration: Any, plan: Any | None) -> DoctorCheck:
    items = _path_items(configuration, plan)
    missing: list[str] = []
    wrong_type: list[str] = []
    for label, path, directory in items:
        try:
            exists = path.exists()
            valid = path.is_dir() if directory else path.is_file()
        except OSError:
            exists = False
            valid = False
        if not exists:
            missing.append(label)
        elif not valid:
            wrong_type.append(label)
    if wrong_type:
        return DoctorCheck(
            "paths",
            STATUS_FAIL,
            f"{len(wrong_type)} configured path(s) have the wrong type",
        )
    if missing:
        return DoctorCheck(
            "paths",
            STATUS_WARN,
            f"{len(missing)} configured path(s) are not present",
        )
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
    configuration, error = _load_configuration(path, env) if path.is_file() else (None, None)
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

    checks.append(_check_paths(configuration, plan))
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
    json_output: bool = False,
    output: Callable[[str], Any] = print,
) -> int:
    """Run and render the doctor, returning a process-style exit code."""

    report = check(profile, environ=environ, probe=probe)
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

    parser = argparse.ArgumentParser(description="Run the offline Oratrice self-check")
    parser.add_argument(
        "--profile",
        default=str(Path(__file__).resolve().parents[1] / "config" / "profiles" / "live.yaml"),
    )
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args(argv)
    return run_doctor(args.profile, probe=args.probe, json_output=args.json_output)


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
