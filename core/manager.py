# -*- coding: utf-8 -*-
"""Resource and runtime compatibility facade.

Resource lookup remains delegated to ``ResourceRegistry``.  Runtime process
control is delegated to the explicit lifecycle manager while the historical
``start``/``stop``/``status`` and model methods continue to work for existing
frontends.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from core.runtime_launcher import RuntimeLauncher
from core.runtime_manager import RuntimeStatus


def _resource_value(resource: Any, key: str, default: Any = None) -> Any:
    if resource is None:
        return default
    getter = getattr(resource, "get", None)
    if callable(getter):
        try:
            value = getter(key, default)
        except TypeError:
            value = getter(key)
        if value is not None:
            return value
    if isinstance(resource, Mapping):
        return resource.get(key, default)
    return getattr(resource, key, default)


def _runtime_id(runtime: Any) -> str:
    if isinstance(runtime, str):
        return runtime
    value = _resource_value(runtime, "id")
    if value is None:
        value = _resource_value(runtime, "runtime_id")
    if value is None:
        raise ValueError("Runtime is missing an id")
    return str(value)


def _legacy_status(value: Any) -> str:
    """Convert either a detailed status or old string status to two states."""

    if isinstance(value, str):
        return value
    if isinstance(value, RuntimeStatus):
        return "running" if value.is_running else "stopped"
    state = getattr(value, "state", None)
    if state is not None:
        state_value = getattr(state, "value", state)
        return "running" if state_value in {"starting", "running", "ready"} else "stopped"
    return "running" if bool(value) else "stopped"


class ResourceManager:
    """Registry facade plus backward-compatible runtime operations.

    ``runtime_launcher``/``runtime_manager`` may be supplied for dependency
    injection.  Alternatively, runtime manager constructor options such as
    ``process_runner`` and ``http_probe`` can be passed directly.
    """

    def __init__(
        self,
        registry: Any,
        runtime_launcher: Any = None,
        *,
        runtime_manager: Any = None,
        runtime_controller: Any = None,
        **runtime_options: Any,
    ):
        self.registry = registry
        supplied = runtime_manager or runtime_controller or runtime_launcher
        self.runtime_launcher = (
            supplied if supplied is not None else RuntimeLauncher(**runtime_options)
        )
        # New consumers can use the descriptive name without breaking callers
        # that still access ``runtime_launcher`` directly.
        self.runtime_manager = self.runtime_launcher

    def get(self, resource_id):
        return self.registry.get(resource_id)

    def exists(self, resource_id):
        return self.registry.exists(resource_id)

    def list_models(self):
        return self.registry.list_models()

    def list_runtimes(self):
        return self.registry.list_runtimes()

    def list_services(self):
        return self.registry.list_services()

    def list_apps(self):
        return self.registry.list_apps()

    def list_system(self):
        return self.registry.list_system()

    # ----- Runtime operations (by runtime_id) -----

    def start(self, runtime_id: str, **kwargs: Any):
        runtime = self.get(runtime_id)
        if runtime is None:
            raise ValueError(f"Runtime not found: {runtime_id}")
        return self.runtime_launcher.start(runtime, **kwargs)

    def stop(self, runtime_id: str, **kwargs: Any):
        return self.runtime_launcher.stop(runtime_id, **kwargs)

    def restart(self, runtime_id: str, **kwargs: Any):
        runtime = self.get(runtime_id)
        if runtime is None:
            raise ValueError(f"Runtime not found: {runtime_id}")
        return self.runtime_launcher.restart(runtime, **kwargs)

    def status(self, runtime_id: str) -> str:
        return _legacy_status(self.runtime_launcher.status(runtime_id))

    def status_info(self, runtime_id: str) -> RuntimeStatus | Any:
        status_info = getattr(self.runtime_launcher, "status_info", None)
        if callable(status_info):
            return status_info(runtime_id)
        status = self.runtime_launcher.status(runtime_id)
        return status

    get_status = status_info

    # ----- Model operations (by model_id, auto-detect runtime) -----

    def _get_runtime_for_model(self, model_id: str):
        model = self.get(model_id)
        if model is None:
            raise ValueError(f"Model not found: {model_id}")

        runtime_id = _resource_value(model, "runtime") or _resource_value(model, "runtime_id")
        if not runtime_id:
            raise ValueError(f"Model {model_id} has no 'runtime' field")

        runtime = self.get(runtime_id)
        if runtime is None:
            raise ValueError(f"Runtime '{runtime_id}' not found for model {model_id}")
        return runtime

    def _runtime_process(self, runtime: Any):
        rid = _runtime_id(runtime)
        processes = getattr(self.runtime_launcher, "processes", {})
        process = processes.get(rid) if hasattr(processes, "get") else None
        if process is not None:
            poll = getattr(process, "poll", None)
            if not callable(poll) or poll() is None:
                return process
        return None

    def start_model(
        self,
        model_id: str,
        *,
        timeout: float | None = None,
        readiness_timeout: float | None = None,
        wait_for_ready: bool | None = None,
        readiness: bool | None = None,
    ):
        model = self.get(model_id)
        if model is None:
            raise ValueError(f"Model not found: {model_id}")

        runtime = self._get_runtime_for_model(model_id)
        existing = self._runtime_process(runtime)
        if existing is not None:
            return existing

        model_path = _resource_value(model, "path")
        if not model_path:
            raise ValueError(f"Model {model_id} has no 'path'")
        model_path = Path(model_path)
        model_arg = str(model_path.absolute())

        # Only model-specific arguments are appended.  Runtime args remain
        # configured on the runtime and are not duplicated.
        extra_args: list[str] = ["--model", model_arg]
        ctx_size = _resource_value(model, "ctx_size")
        if ctx_size:
            extra_args.extend(["-c", str(ctx_size)])

        options: dict[str, Any] = {}
        if timeout is not None:
            options["timeout"] = timeout
        if readiness_timeout is not None:
            options["readiness_timeout"] = readiness_timeout
        if wait_for_ready is not None:
            options["wait_for_ready"] = wait_for_ready
        if readiness is not None:
            options["readiness"] = readiness
        return self.runtime_launcher.start(runtime, extra_args=extra_args, **options)

    def stop_model(self, model_id: str, **kwargs: Any):
        runtime = self._get_runtime_for_model(model_id)
        return self.runtime_launcher.stop(_runtime_id(runtime), **kwargs)

    def restart_model(self, model_id: str, **kwargs: Any):
        model = self.get(model_id)
        if model is None:
            raise ValueError(f"Model not found: {model_id}")
        runtime = self._get_runtime_for_model(model_id)
        model_path = _resource_value(model, "path")
        if not model_path:
            raise ValueError(f"Model {model_id} has no 'path'")
        extra_args: list[str] = ["--model", str(Path(model_path).absolute())]
        ctx_size = _resource_value(model, "ctx_size")
        if ctx_size:
            extra_args.extend(["-c", str(ctx_size)])
        return self.runtime_launcher.restart(runtime, extra_args=extra_args, **kwargs)

    def status_model(self, model_id: str) -> str:
        runtime = self._get_runtime_for_model(model_id)
        return self.status(_runtime_id(runtime))

    def status_model_info(self, model_id: str) -> RuntimeStatus | Any:
        runtime = self._get_runtime_for_model(model_id)
        return self.status_info(_runtime_id(runtime))


__all__ = ["ResourceManager"]
