"""Configuration-driven readiness probes for externally owned services.

The provider is deliberately lazy: construction stores only the profile path.
The profile is parsed and its launcher endpoints are probed only when the API
invokes the provider for ``/ready``.  It reports target IDs and HTTP outcomes,
never environment values or raw transport exception messages.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
import urllib.request

import yaml


EndpointOpener = Callable[[str, float, Mapping[str, str]], Any]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _target_id(value: Mapping[str, Any], index: int) -> str:
    candidate = value.get("id")
    text = str(candidate).strip() if candidate is not None else ""
    return text or f"target_{index}"


def _safe_endpoint(value: Any) -> str | None:
    """Return a display-safe endpoint without query, fragment, or credentials."""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    try:
        host = parsed.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        netloc = host
        if parsed.port is not None:
            netloc = f"{netloc}:{parsed.port}"
        return urlunsplit((parsed.scheme, netloc, parsed.path or "/", "", ""))
    except ValueError:
        return None


def _response_status(response: Any) -> int | None:
    if isinstance(response, Mapping):
        value = response.get("status_code", response.get("status"))
    else:
        value = getattr(response, "status_code", getattr(response, "status", None))
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class ExternalEndpointReadinessProvider:
    """Probe declarative launcher target health endpoints on demand.

    ``opener`` is injectable for deterministic contract tests and must accept
    ``(endpoint, timeout, headers)``.  The default uses a standard-library
    HTTP GET.  No file, environment, process, socket, or network access occurs
    in ``__init__``.
    """

    def __init__(
        self,
        config_path: str | Path,
        *,
        opener: EndpointOpener | None = None,
        environ: Mapping[str, str] | None = None,
        timeout: float = 2.0,
    ) -> None:
        self.config_path = Path(config_path).expanduser()
        self.opener = opener or self._open
        self.environ = environ if environ is not None else os.environ
        self.timeout = max(0.1, float(timeout))

    def __call__(self, **_: Any) -> Mapping[str, Any]:
        return self.check_readiness()

    def check_readiness(self) -> Mapping[str, Any]:
        """Load the profile and probe the default required launcher targets."""

        try:
            profile = self._load_profile()
            defaults = _mapping(profile.get("defaults"))
            launcher = _mapping(defaults.get("launcher"))
        except Exception as exc:
            return self._failure("configuration", type(exc).__name__)

        required_targets = list(_sequence(launcher.get("targets")))
        if not required_targets:
            return self._failure("configuration", "NoLauncherTargets")

        components: dict[str, Any] = {}
        required_ids: list[str] = []
        # Only ``targets`` are part of the default release scope.  Entries in
        # ``optional_targets`` are selected by an explicit launcher flag and
        # there is no cross-process selection signal in the API process; they
        # therefore remain deferred instead of degrading every default run.
        for index, raw_target in enumerate(required_targets):
            target = _mapping(raw_target)
            target_id = _target_id(target, index)
            if target_id not in components:
                required_ids.append(target_id)
            components[target_id] = self._probe_target(target, optional=False)

        required_ok = all(
            bool(components[target_id].get("healthy")) for target_id in required_ids
        )
        if not required_ok:
            status, healthy = "not_ready", False
        else:
            status, healthy = "healthy", True
        return {
            "report": {
                "status": status,
                "healthy": healthy,
                "components": {"launcher": components},
                "details": {"source": "defaults.launcher"},
            },
            "required": required_ids,
            "optional": [],
        }

    def _load_profile(self) -> Mapping[str, Any]:
        with self.config_path.open("r", encoding="utf-8") as stream:
            value = yaml.safe_load(stream)
        profile = _mapping(value)
        if not profile:
            raise ValueError("profile must be a mapping")
        return profile

    def _probe_target(self, target: Mapping[str, Any], *, optional: bool) -> dict[str, Any]:
        endpoint_value = target.get("health_endpoint")
        endpoint = _safe_endpoint(endpoint_value)
        result: dict[str, Any] = {
            "status": "unhealthy",
            "healthy": False,
            "optional": optional,
        }
        if endpoint is not None:
            result["endpoint"] = endpoint
        if endpoint is None:
            result["error"] = "InvalidHealthEndpoint"
            return result
        required_env = tuple(
            name
            for name in _sequence(target.get("required_env"))
            if isinstance(name, str) and name
        )
        if any(not self.environ.get(name) for name in required_env):
            result["error"] = "MissingEnvironment"
            return result
        headers: dict[str, str] = {}
        if required_env:
            # Match the launcher's health-probe contract.  The value exists
            # only in the request header and is never copied into the report.
            headers["Authorization"] = "Bearer " + self.environ[required_env[0]]
        path = urlsplit(endpoint).path.rstrip("/") or "/"
        if path == "/ready":
            result["error"] = "RecursiveReadinessEndpoint"
            return result
        try:
            response = self.opener(endpoint, self._target_timeout(target), headers)
            status_code = _response_status(response)
            if status_code is not None:
                result["http_status"] = status_code
            if status_code is not None and 200 <= status_code < 400:
                result["status"] = "healthy"
                result["healthy"] = True
            else:
                result["error"] = "UnhealthyEndpoint"
        except Exception as exc:
            # Do not include exception strings: they can contain URLs or
            # credentials supplied by a transport implementation.
            result["error"] = type(exc).__name__
        return result

    def _target_timeout(self, target: Mapping[str, Any]) -> float:
        value = target.get("health_timeout", target.get("probe_timeout"))
        try:
            return max(0.1, float(value)) if value is not None else self.timeout
        except (TypeError, ValueError):
            return self.timeout

    @staticmethod
    def _open(endpoint: str, timeout: float, headers: Mapping[str, str]) -> Any:
        request = urllib.request.Request(endpoint, headers=dict(headers), method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {"status_code": int(response.getcode())}

    @staticmethod
    def _failure(component: str, error: str) -> Mapping[str, Any]:
        return {
            "report": {
                "status": "not_ready",
                "healthy": False,
                "components": {component: {"status": "unhealthy", "healthy": False, "error": error}},
                "details": {"source": "defaults.launcher"},
            },
            "required": [component],
            "optional": [],
        }


EndpointReadinessProvider = ExternalEndpointReadinessProvider


__all__ = ["EndpointReadinessProvider", "ExternalEndpointReadinessProvider"]
