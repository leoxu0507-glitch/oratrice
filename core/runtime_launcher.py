# -*- coding: utf-8 -*-
"""Compatibility adapter for the runtime lifecycle manager.

``RuntimeLauncher`` preserves the original ``start``/``stop``/``status``
surface used by ``ResourceManager`` and older frontends.  New code can import
``RuntimeManager`` and inspect detailed ``RuntimeStatus`` objects directly.
"""

from __future__ import annotations

from typing import Any, Sequence

from core.runtime_manager import (
    RuntimeConfigurationError,
    RuntimeLifecycleError,
    RuntimeManager,
    RuntimePortConflictError,
    RuntimeReadinessTimeout,
    RuntimeStartError,
    RuntimeStartupError,
    RuntimeState,
    RuntimeStatus,
    RuntimeTimeoutError,
)


class RuntimeLauncher(RuntimeManager):
    """Legacy string-status facade over :class:`RuntimeManager`.

    The old implementation returned a ``Popen`` handle from ``start`` and
    ``None`` from ``stop``.  Those return values remain unchanged; detailed
    state is available through ``status_info``/``get_status``.
    """

    def start(
        self,
        runtime: Any,
        extra_args: Sequence[Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        # ``RuntimeLauncher`` is the historical, fire-and-return adapter.  A
        # port in legacy ``args`` is not by itself a readiness contract: the
        # previous launcher returned immediately after ``Popen``.  Preserve
        # that behavior unless the caller/configuration explicitly asks for a
        # readiness wait or a probe was injected.  ``RuntimeManager`` itself
        # keeps its richer default (derived endpoints are probed).
        if not self._readiness_requested(runtime, kwargs):
            kwargs["wait_for_ready"] = False
        return super().start(runtime, extra_args=extra_args, **kwargs)

    def _readiness_requested(self, runtime: Any, kwargs: dict[str, Any]) -> bool:
        if self.http_probe is not None:
            return True
        if any(
            key in kwargs
            for key in ("wait_for_ready", "readiness", "timeout", "readiness_timeout")
        ):
            return True
        # These fields are an explicit readiness contract.  Do not treat a
        # bare ``--port`` argument as one; that is the common legacy config.
        for key in (
            "readiness_url",
            "ready_url",
            "health_url",
            "probe_url",
            "health_endpoint",
            "health_path",
            "readiness_path",
            "endpoint",
            "base_url",
            "readiness",
            "wait_for_ready",
        ):
            value = self._runtime_value(runtime, key)
            if value is not None and value != "":
                return True
        return False

    @staticmethod
    def _runtime_value(runtime: Any, key: str) -> Any:
        getter = getattr(runtime, "get", None)
        if callable(getter):
            try:
                return getter(key, None)
            except TypeError:
                return getter(key)
        if isinstance(runtime, dict):
            return runtime.get(key)
        return getattr(runtime, key, None)

    def stop(self, runtime_id: Any, **kwargs: Any) -> None:
        super().stop(runtime_id, **kwargs)
        # Preserve the historical return value.
        return None

    def status(self, runtime_id: Any) -> str:
        return self.legacy_status(runtime_id)

    def status_info(self, runtime_id: Any) -> RuntimeStatus:
        return super().status(runtime_id)

    get_status = status_info


__all__ = [
    "RuntimeLauncher",
    "RuntimeManager",
    "RuntimeState",
    "RuntimeStatus",
    "RuntimeLifecycleError",
    "RuntimeConfigurationError",
    "RuntimeStartError",
    "RuntimeStartupError",
    "RuntimePortConflictError",
    "RuntimeTimeoutError",
    "RuntimeReadinessTimeout",
]
