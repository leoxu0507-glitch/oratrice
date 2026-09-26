"""Configuration-driven process orchestration for the M2 launcher."""

from __future__ import annotations

import inspect
import os
import secrets
import urllib.request
import webbrowser
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from typing import Any

from core.runtime_manager import RuntimeManager

from .plan import LaunchPlan, LaunchTarget


class LauncherError(RuntimeError):
    """Raised for launcher misuse or failed environment preflight."""


@dataclass(frozen=True, slots=True)
class TargetOutcome:
    id: str
    runtime_id: str
    status: str
    optional: bool
    owned: bool = False
    command: tuple[str, ...] = ()
    error_type: str | None = None


@dataclass(frozen=True, slots=True)
class LaunchResult:
    status: str
    outcomes: tuple[TargetOutcome, ...]
    ui_status: str
    dry_run: bool = False

    @property
    def ok(self) -> bool:
        return self.status == "PASS"


class LauncherOrchestrator:
    """Start a launch plan in order and stop only manager-owned processes."""

    def __init__(
        self,
        configuration: Any,
        *,
        plan: LaunchPlan | None = None,
        runtime_manager: Any = None,
        health_probe: Callable[..., Any] | None = None,
        browser_opener: Callable[[str], Any] | None = None,
        env: MutableMapping[str, str] | None = None,
        secret_factory: Callable[[], str] | None = None,
    ) -> None:
        self.configuration = configuration
        self.plan = plan or LaunchPlan.from_configuration(configuration)
        self.env = env if env is not None else os.environ
        self.health_probe = health_probe or self._default_health_probe
        self.browser_opener = browser_opener or webbrowser.open
        self.secret_factory = secret_factory or (lambda: secrets.token_urlsafe(32))
        self._health_headers: dict[str, dict[str, str]] = {}
        self.runtime_manager = runtime_manager or RuntimeManager(http_probe=self._runtime_probe)
        self._generated_names: set[str] = set()
        self._active = False

    def start(
        self,
        *,
        include_optional: Sequence[str] = (),
        dry_run: bool = False,
        open_ui: bool = True,
    ) -> LaunchResult:
        if self._active:
            raise LauncherError("launcher is already active")
        targets = self.plan.selected_targets(include_optional)
        if dry_run:
            outcomes = tuple(
                TargetOutcome(
                    target.id,
                    target.runtime_id,
                    "PLANNED",
                    target.optional,
                    command=self._command(self._runtime_spec(target, include_env=False)),
                )
                for target in targets
            )
            return LaunchResult("PASS", outcomes, "NOT_REQUESTED", dry_run=True)

        self._active = True
        outcomes: list[TargetOutcome] = []
        try:
            for target in targets:
                try:
                    self._prepare_environment(target)
                    runtime = self._runtime_spec(target, include_env=True)
                    command = self._command(runtime)
                    self._register_health_headers(target)
                    if target.health_endpoint and self._probe(target.health_endpoint, 1.0):
                        outcomes.append(
                            TargetOutcome(
                                target.id,
                                target.runtime_id,
                                "REUSED_EXTERNAL",
                                target.optional,
                                command=command,
                            )
                        )
                        continue
                    self.runtime_manager.start(
                        runtime,
                        wait_for_ready=True,
                        timeout=target.timeout,
                    )
                    outcomes.append(
                        TargetOutcome(
                            target.id,
                            target.runtime_id,
                            "STARTED",
                            target.optional,
                            owned=True,
                            command=command,
                        )
                    )
                except Exception as exc:
                    outcomes.append(
                        TargetOutcome(
                            target.id,
                            target.runtime_id,
                            "SKIPPED" if target.optional else "FAILED",
                            target.optional,
                            error_type=type(exc).__name__,
                        )
                    )
                    if target.optional:
                        continue
                    self.runtime_manager.stop_all()
                    self._restore_generated_environment()
                    self._active = False
                    return LaunchResult("FAIL", tuple(outcomes), "NOT_REQUESTED")
            return LaunchResult("PASS", tuple(outcomes), self._open_ui(open_ui))
        except Exception:
            self.runtime_manager.stop_all()
            self._restore_generated_environment()
            self._active = False
            raise

    def stop(self) -> Any:
        try:
            return self.runtime_manager.stop_all()
        finally:
            self._restore_generated_environment()
            self._active = False

    close = stop

    def __enter__(self) -> "LauncherOrchestrator":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.stop()

    def _prepare_environment(self, target: LaunchTarget) -> None:
        for name in target.required_env:
            if self.env.get(name):
                continue
            if not target.generate_if_missing:
                raise LauncherError(f"required environment variable {name!r} is not set")
            value = self.secret_factory()
            if not isinstance(value, str) or not value:
                raise LauncherError("secret_factory returned an empty value")
            self.env[name] = value
            self._generated_names.add(name)

    def _restore_generated_environment(self) -> None:
        for name in tuple(self._generated_names):
            self.env.pop(name, None)
        self._generated_names.clear()
        self._health_headers.clear()

    def _register_health_headers(self, target: LaunchTarget) -> None:
        if target.health_endpoint and target.required_env:
            value = self.env.get(target.required_env[0])
            if value:
                self._health_headers[target.health_endpoint] = {
                    "Authorization": "Bearer " + value
                }

    def _runtime_spec(self, target: LaunchTarget, *, include_env: bool) -> dict[str, Any]:
        runtime = self.configuration.runtimes[target.runtime_id]
        options = dict(getattr(runtime, "options", {}) or {})
        if target.health_endpoint:
            options["health_endpoint"] = target.health_endpoint
        if include_env:
            process_env = dict(self.env)
            process_env.update(target.environment)
            options["env"] = process_env
        executable = target.executable_override or getattr(runtime, "executable", None)
        args = _override_arguments(
            tuple(getattr(runtime, "args", ()) or ()), target.argument_overrides
        )
        return {
            "id": target.runtime_id,
            "name": getattr(runtime, "name", target.id),
            "type": getattr(runtime, "type", "executable"),
            "executable": executable,
            "working_dir": getattr(runtime, "working_dir", None),
            "args": list(args),
            "provider": getattr(runtime, "provider", None),
            "enabled": getattr(runtime, "enabled", True),
            **options,
        }

    @staticmethod
    def _command(runtime: Mapping[str, Any]) -> tuple[str, ...]:
        return (
            str(runtime.get("executable")),
            *(str(value) for value in runtime.get("args", ())),
        )

    def _runtime_probe(self, endpoint: str, timeout: float | None = None) -> bool:
        return self._probe(endpoint, timeout or 2.0)

    def _probe(self, endpoint: str, timeout: float) -> bool:
        headers = self._health_headers.get(endpoint, {})
        probe = self.health_probe
        try:
            signature = inspect.signature(probe)
        except (TypeError, ValueError):
            signature = None
        try:
            if signature is None or any(
                parameter.kind is inspect.Parameter.VAR_POSITIONAL
                for parameter in signature.parameters.values()
            ) or len(signature.parameters) >= 3:
                response = probe(endpoint, timeout, dict(headers))
            else:
                response = probe(endpoint, timeout)
        except Exception:
            return False
        return _probe_succeeded(response)

    @staticmethod
    def _default_health_probe(
        endpoint: str,
        timeout: float,
        headers: Mapping[str, str] | None = None,
    ) -> int:
        request = urllib.request.Request(endpoint, headers=dict(headers or {}))
        with urllib.request.urlopen(
            request, timeout=max(0.1, min(float(timeout), 5.0))
        ) as response:
            return int(response.getcode())

    def _open_ui(self, requested: bool) -> str:
        if not requested or not self.plan.open_ui_if_available:
            return "NOT_REQUESTED"
        if not self._probe(self.plan.ui_health_url, 1.0):
            return "SKIPPED_UNAVAILABLE"
        try:
            self.browser_opener(self.plan.ui_url)
            return "OPENED"
        except Exception:
            return "OPEN_FAILED"


def _override_arguments(
    args: Sequence[str], overrides: Mapping[str, str]
) -> tuple[str, ...]:
    result = [str(value) for value in args]
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


def _probe_succeeded(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return 200 <= value < 300
    status_code = getattr(value, "status_code", None)
    if status_code is not None:
        try:
            return 200 <= int(status_code) < 300
        except (TypeError, ValueError):
            return False
    if isinstance(value, Mapping):
        if "status_code" in value:
            try:
                return 200 <= int(value["status_code"]) < 300
            except (TypeError, ValueError):
                return False
        return str(value.get("status", "")).lower() in {"ok", "ready", "healthy"}
    return False


__all__ = ["LaunchResult", "LauncherError", "LauncherOrchestrator", "TargetOutcome"]
