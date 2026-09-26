"""Immutable, configuration-driven startup plans for Oratrice.

This module parses already validated :class:`core.configuration.Configuration`
objects.  It has no process, network, browser, or environment side effects;
those responsibilities belong to the M2 orchestration boundary.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import urlparse


_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class LaunchPlanError(ValueError):
    """Raised when ``defaults.launcher`` is missing or malformed."""


@dataclass(frozen=True, slots=True)
class LaunchTarget:
    """One runtime selected by a launch plan."""

    id: str
    runtime_id: str
    timeout: float
    required_env: tuple[str, ...] = ()
    environment: Mapping[str, str] = MappingProxyType({})
    argument_overrides: Mapping[str, str] = MappingProxyType({})
    executable_override: Path | None = None
    health_endpoint: str | None = None
    before: str | None = None
    optional: bool = False
    generate_if_missing: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "argument_overrides",
            MappingProxyType(dict(self.argument_overrides)),
        )
        object.__setattr__(
            self,
            "environment",
            MappingProxyType(dict(self.environment)),
        )


@dataclass(frozen=True, slots=True)
class LaunchPlan:
    """Ordered default and optional runtime targets."""

    targets: tuple[LaunchTarget, ...]
    optional_targets: tuple[LaunchTarget, ...]
    ui_url: str
    ui_health_url: str
    open_ui_if_available: bool = True
    attempt_limit: int = 3

    @classmethod
    def from_configuration(cls, configuration: Any) -> "LaunchPlan":
        defaults = getattr(configuration, "defaults", None)
        if not isinstance(defaults, Mapping):
            raise LaunchPlanError("configuration defaults must be a mapping")
        raw = defaults.get("launcher")
        if not isinstance(raw, Mapping):
            raise LaunchPlanError("defaults.launcher must be a mapping")

        runtimes = getattr(configuration, "runtimes", None)
        if not isinstance(runtimes, Mapping):
            raise LaunchPlanError("configuration runtimes must be a mapping")

        targets = _targets(raw.get("targets"), runtimes, optional=False, label="targets")
        optional_targets = _targets(
            raw.get("optional_targets", ()),
            runtimes,
            optional=True,
            label="optional_targets",
        )
        all_ids = [target.id for target in (*targets, *optional_targets)]
        duplicates = sorted({value for value in all_ids if all_ids.count(value) > 1})
        if duplicates:
            raise LaunchPlanError("duplicate launcher target id(s): " + ", ".join(duplicates))
        required_ids = {target.id for target in targets}
        for target in optional_targets:
            if target.before is not None and target.before not in required_ids:
                raise LaunchPlanError(
                    f"optional launcher target {target.id!r} references unknown before target {target.before!r}"
                )

        ui_url = _url(raw.get("ui_url"), "defaults.launcher.ui_url")
        ui_health_url = _url(
            raw.get("ui_health_url", ui_url),
            "defaults.launcher.ui_health_url",
        )
        open_ui = raw.get("open_ui_if_available", True)
        if not isinstance(open_ui, bool):
            raise LaunchPlanError("defaults.launcher.open_ui_if_available must be boolean")
        attempt_limit = raw.get("attempt_limit", 3)
        if isinstance(attempt_limit, bool) or not isinstance(attempt_limit, int) or attempt_limit < 1:
            raise LaunchPlanError("defaults.launcher.attempt_limit must be a positive integer")

        return cls(
            targets=targets,
            optional_targets=optional_targets,
            ui_url=ui_url,
            ui_health_url=ui_health_url,
            open_ui_if_available=open_ui,
            attempt_limit=attempt_limit,
        )

    def selected_targets(self, include_optional: Sequence[str] = ()) -> tuple[LaunchTarget, ...]:
        """Merge explicitly selected optional targets into configured order."""

        requested = set(include_optional)
        known = {target.id for target in self.optional_targets}
        unknown = requested - known
        if unknown:
            raise LaunchPlanError("unknown optional launcher target(s): " + ", ".join(sorted(unknown)))
        ordered = list(self.targets)
        for target in self.optional_targets:
            if target.id not in requested:
                continue
            if target.before is None:
                ordered.append(target)
            else:
                index = next(i for i, item in enumerate(ordered) if item.id == target.before)
                ordered.insert(index, target)
        return tuple(ordered)


def _targets(
    value: Any,
    runtimes: Mapping[str, Any],
    *,
    optional: bool,
    label: str,
) -> tuple[LaunchTarget, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise LaunchPlanError(f"defaults.launcher.{label} must be a list")
    result: list[LaunchTarget] = []
    for index, item in enumerate(value):
        location = f"defaults.launcher.{label}[{index}]"
        if not isinstance(item, Mapping):
            raise LaunchPlanError(f"{location} must be a mapping")
        target_id = _text(item.get("id"), f"{location}.id")
        runtime_id = _text(item.get("runtime"), f"{location}.runtime")
        if runtime_id not in runtimes:
            raise LaunchPlanError(f"{location}.runtime references unknown runtime {runtime_id!r}")
        timeout = item.get("timeout", 120)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise LaunchPlanError(f"{location}.timeout must be a positive number")
        timeout = float(timeout)
        if not math.isfinite(timeout) or timeout <= 0:
            raise LaunchPlanError(f"{location}.timeout must be a positive number")

        required_env_value = item.get("required_env", ())
        if not isinstance(required_env_value, Sequence) or isinstance(
            required_env_value, (str, bytes, bytearray)
        ):
            raise LaunchPlanError(f"{location}.required_env must be a list")
        required_env: list[str] = []
        for env_index, name in enumerate(required_env_value):
            if not isinstance(name, str) or not _ENV_NAME.fullmatch(name):
                raise LaunchPlanError(
                    f"{location}.required_env[{env_index}] must be an environment-variable name"
                )
            if name not in required_env:
                required_env.append(name)

        environment_value = item.get("environment", {})
        if not isinstance(environment_value, Mapping):
            raise LaunchPlanError(f"{location}.environment must be a mapping")
        environment: dict[str, str] = {}
        for name, value in environment_value.items():
            if not isinstance(name, str) or not _ENV_NAME.fullmatch(name):
                raise LaunchPlanError(
                    f"{location}.environment keys must be environment-variable names"
                )
            if not isinstance(value, (str, int, float)) or isinstance(value, bool):
                raise LaunchPlanError(
                    f"{location}.environment[{name!r}] must be scalar"
                )
            environment[name] = str(value)

        overrides_value = item.get("argument_overrides", {})
        if not isinstance(overrides_value, Mapping):
            raise LaunchPlanError(f"{location}.argument_overrides must be a mapping")
        overrides: dict[str, str] = {}
        for key, override in overrides_value.items():
            if not isinstance(key, str) or not key.strip():
                raise LaunchPlanError(f"{location}.argument_overrides keys must be non-empty strings")
            if not isinstance(override, (str, int, float)) or isinstance(override, bool):
                raise LaunchPlanError(f"{location}.argument_overrides[{key!r}] must be scalar")
            overrides[key.strip()] = str(override)

        executable = item.get("executable_override")
        if executable is not None:
            executable = Path(executable)
            if not executable.is_absolute():
                raise LaunchPlanError(f"{location}.executable_override must resolve to an absolute path")

        health_endpoint_value = item.get("health_endpoint")
        health_endpoint = (
            _url(health_endpoint_value, f"{location}.health_endpoint")
            if health_endpoint_value is not None
            else None
        )

        generate = item.get("generate_if_missing", False)
        if not isinstance(generate, bool):
            raise LaunchPlanError(f"{location}.generate_if_missing must be boolean")
        if generate and not required_env:
            raise LaunchPlanError(f"{location}.generate_if_missing requires required_env")

        before_value = item.get("before")
        before = _text(before_value, f"{location}.before") if before_value is not None else None

        result.append(
            LaunchTarget(
                id=target_id,
                runtime_id=runtime_id,
                timeout=timeout,
                required_env=tuple(required_env),
                environment=environment,
                argument_overrides=overrides,
                executable_override=executable,
                health_endpoint=health_endpoint,
                before=before,
                optional=optional,
                generate_if_missing=generate,
            )
        )
    if not optional and not result:
        raise LaunchPlanError("defaults.launcher.targets must not be empty")
    return tuple(result)


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LaunchPlanError(f"{label} must be a non-empty string")
    return value.strip()


def _url(value: Any, label: str) -> str:
    value = _text(value, label)
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise LaunchPlanError(f"{label} must be an absolute HTTP(S) URL")
    return value


__all__ = ["LaunchPlan", "LaunchPlanError", "LaunchTarget"]
