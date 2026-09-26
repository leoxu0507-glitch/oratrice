#!/usr/bin/env python3
"""Explicit, opt-in live verification for Oratrice.

The normal pytest suite is intentionally offline.  This module is a small
stand-alone command line harness for release checks against already-running
endpoints.  It never starts a model process.  Network I/O is only enabled by
the explicit ``--live`` switch; ``--dry-run`` and ``--fake`` are safe to use
in CI and on developer machines without model credentials.

The implementation deliberately does not import ``core``/``router`` during
module import.  That keeps the command useful while the application wiring is
being migrated and prevents an accidental runtime start as a side effect of
inspection (including ``--help``).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit


COMPONENTS: tuple[str, ...] = (
    "runtime-gpt",
    "runtime-gemma",
    "gateway-gpt",
    "core-text",
    "qwen-vision",
    "deepseek-cloud",
)

_COMPONENT_ALIASES = {
    "runtime_gpt": "runtime-gpt",
    "runtime-gemma": "runtime-gemma",
    "runtime_gemma": "runtime-gemma",
    "gateway_gpt": "gateway-gpt",
    "core_text": "core-text",
    "qwen_vision": "qwen-vision",
    "deepseek_cloud": "deepseek-cloud",
    "qwen": "qwen-vision",
    "deepseek": "deepseek-cloud",
}

_SECRET_NAME = re.compile(r"(?:api[-_]?key|token|secret|password|authorization|credential)", re.I)
_ENV_REF = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$|^\$([A-Za-z_][A-Za-z0-9_]*)$")


class LiveConfigError(ValueError):
    """A profile/environment value is missing or malformed."""


@dataclass(frozen=True)
class ComponentSpec:
    name: str
    cloud: bool = False
    health_only: bool = False
    vision: bool = False


_SPECS = {
    "runtime-gpt": ComponentSpec("runtime-gpt", health_only=True),
    "runtime-gemma": ComponentSpec("runtime-gemma", health_only=True),
    "gateway-gpt": ComponentSpec("gateway-gpt"),
    "core-text": ComponentSpec("core-text"),
    "qwen-vision": ComponentSpec("qwen-vision", vision=True),
    "deepseek-cloud": ComponentSpec("deepseek-cloud", cloud=True),
}


@dataclass(frozen=True)
class TargetConfig:
    """Resolved values for one component.

    ``api_key`` is intentionally excluded from ``repr`` so accidental debug
    output cannot expose credentials.  The value is only used to construct an
    Authorization header immediately before a live request.
    """

    component: str
    endpoint: str | None = None
    model: str | None = None
    timeout: float = 30.0
    api_key: str | None = field(default=None, repr=False)
    image_path: str | None = None
    source: str = "defaults"


@dataclass(frozen=True)
class CheckResult:
    component: str
    layer: str
    status: str
    detail: str
    elapsed_ms: float | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "component": self.component,
            "layer": self.layer,
            "status": self.status,
            "detail": self.detail,
        }
        if self.elapsed_ms is not None:
            result["elapsed_ms"] = round(self.elapsed_ms, 1)
        return result


def _root_dir() -> Path:
    # scripts/live_verify.py -> project root
    return Path(__file__).resolve().parents[1]


def _normalise_component(value: str) -> str:
    value = value.strip().lower().replace("/", "-")
    value = _COMPONENT_ALIASES.get(value, value)
    if value not in COMPONENTS:
        valid = ", ".join(COMPONENTS)
        raise LiveConfigError(f"unknown component {value!r}; choose one of: {valid}")
    return value


def parse_components(values: Sequence[str] | None, *, default_all: bool = True) -> list[str]:
    """Parse repeated/comma-separated ``--component`` values."""

    if not values:
        return list(COMPONENTS) if default_all else []
    result: list[str] = []
    for item in values:
        for raw in str(item).split(","):
            name = _normalise_component(raw)
            if name not in result:
                result.append(name)
    return result


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _load_profile(path: Path) -> Mapping[str, Any]:
    """Load JSON or YAML without echoing profile contents."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LiveConfigError(f"unable to read live profile ({type(exc).__name__})") from exc
    try:
        if path.suffix.lower() == ".json":
            value = json.loads(text)
        else:
            try:
                import yaml  # type: ignore[import-not-found]
            except ImportError:
                # JSON is valid YAML; this keeps dry-run/fake useful when the
                # optional parser is not installed.
                value = json.loads(text)
            else:
                value = yaml.safe_load(text)
    except Exception as exc:
        raise LiveConfigError(f"live profile is not valid ({type(exc).__name__})") from exc
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise LiveConfigError("live profile root must be a mapping")
    return value


def _candidate_profile_paths(explicit: str | None) -> list[Path]:
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return [path]
    configured = os.getenv("ORATRICE_LIVE_PROFILE") or os.getenv("ORATRICE_LIVE_PROFILE_PATH")
    if configured:
        return _candidate_profile_paths(configured)
    root = _root_dir()
    return [
        root / "config" / "live-profile.yaml",
        root / "config" / "live_profile.yaml",
        root / "config" / "live-profile.yml",
        root / "config" / "live.yaml",
        root / "config" / "live.json",
        root / ".oratrice" / "live-profile.yaml",
    ]


def _find_profile(explicit: str | None, *, required: bool) -> tuple[Mapping[str, Any], Path | None]:
    candidates = _candidate_profile_paths(explicit)
    for candidate in candidates:
        if candidate.is_file():
            return _load_profile(candidate), candidate
    if required:
        if explicit:
            raise LiveConfigError(f"live profile not found: {Path(explicit).name}")
        raise LiveConfigError(
            "live profile not found; set ORATRICE_LIVE_PROFILE or add config/live-profile.yaml"
        )
    return {}, None


def _normalise_key(value: Any) -> str:
    return str(value).strip().lower().replace("-", "_")


def _component_node(profile: Mapping[str, Any], component: str) -> Mapping[str, Any]:
    """Find a component block across the accepted profile shapes."""

    names = {component, component.replace("-", "_"), component.replace("-", "")}
    containers: list[Mapping[str, Any]] = [profile]
    for key in ("components", "targets", "checks", "live", "profiles"):
        value = _mapping(profile.get(key))
        if value is not None:
            containers.append(value)
    for container in containers:
        for key, value in container.items():
            if _normalise_key(key) in {_normalise_key(name) for name in names}:
                node = _mapping(value)
                if node is not None:
                    return node
    return {}


def _defaults_node(profile: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in ("defaults", "default", "live_defaults"):
        value = _mapping(profile.get(key))
        if value is not None:
            return value
    return {}


def _value(mapping: Mapping[str, Any], names: Sequence[str]) -> Any:
    wanted = {_normalise_key(name) for name in names}
    for key, value in mapping.items():
        if _normalise_key(key) in wanted and value is not None:
            return value
    return None


def _env_value(component: str, field_name: str) -> str | None:
    slug = component.upper().replace("-", "_")
    field_slug = field_name.upper().replace("-", "_")
    candidates = (
        f"ORATRICE_LIVE_{slug}_{field_slug}",
        f"ORATRICE_{slug}_{field_slug}",
        f"ORATRICE_LIVE_{field_slug}",
    )
    for key in candidates:
        value = os.getenv(key)
        if value is not None and value != "":
            return value
    return None


def _resolve_secret(value: Any, *, component: str) -> str | None:
    if value is None:
        value = _env_value(component, "API_KEY")
    if value is None:
        # A conventional cloud key name is useful, but never required for
        # local components and never shown in output.
        if component == "deepseek-cloud":
            value = os.getenv("DEEPSEEK_API_KEY") or os.getenv("DEEPSEEK_KEY")
        else:
            value = os.getenv("ORATRICE_API_KEY")
    if value is None:
        return None
    text = str(value)
    match = _ENV_REF.match(text)
    if match:
        return os.getenv(match.group(1) or match.group(2))
    return text


def _resolve_target(profile: Mapping[str, Any], component: str, *, cli_image: str | None = None) -> TargetConfig:
    defaults = _defaults_node(profile)
    node = _component_node(profile, component)
    merged = dict(defaults)
    merged.update(node)

    endpoint = _value(merged, ("endpoint", "base_url", "baseUrl", "url", "host"))
    model = _value(merged, ("model", "model_id", "modelId"))
    timeout = _value(merged, ("timeout", "timeout_s", "timeout_seconds", "request_timeout"))
    image = cli_image or _value(merged, ("image", "image_path", "image_file", "fixture"))
    api_key_env = _value(merged, ("api_key_env", "token_env", "key_env"))
    api_key = _resolve_secret(_value(merged, ("api_key", "token", "key")), component=component)
    if api_key is None and api_key_env:
        api_key = os.getenv(str(api_key_env))

    env_endpoint = _env_value(component, "ENDPOINT") or _env_value(component, "URL")
    env_model = _env_value(component, "MODEL")
    env_timeout = _env_value(component, "TIMEOUT")
    env_image = _env_value(component, "IMAGE") or _env_value(component, "IMAGE_PATH")
    if env_endpoint is not None:
        endpoint = env_endpoint
    if env_model is not None:
        model = env_model
    if env_timeout is not None:
        timeout = env_timeout
    if env_image is not None and not cli_image:
        image = env_image

    if timeout is None or timeout == "":
        timeout_value = 30.0
    else:
        try:
            timeout_value = float(timeout)
        except (TypeError, ValueError) as exc:
            raise LiveConfigError(f"{component} timeout must be a positive number") from exc
        if timeout_value <= 0 or timeout_value > 600:
            raise LiveConfigError(f"{component} timeout must be between 0 and 600 seconds")

    image_path = None if image is None else str(image)
    if image_path:
        candidate = Path(image_path).expanduser()
        if not candidate.is_absolute():
            profile_path = profile.get("_path") if isinstance(profile, Mapping) else None
            base = Path(profile_path).parent if isinstance(profile_path, str) else Path.cwd()
            candidate = base / candidate
        image_path = str(candidate)

    source = "profile" if node else "environment/defaults"
    return TargetConfig(
        component=component,
        endpoint=None if endpoint is None else str(endpoint).strip(),
        model=None if model is None else str(model).strip(),
        timeout=timeout_value,
        api_key=api_key,
        image_path=image_path,
        source=source,
    )


def _safe_endpoint(endpoint: str | None) -> str:
    """Return a display-safe endpoint (no path/query credentials/userinfo)."""

    if not endpoint:
        return "<unset>"
    try:
        parsed = urlsplit(endpoint)
        if parsed.scheme and parsed.netloc:
            netloc = parsed.hostname or "<host>"
            if parsed.port:
                netloc += f":{parsed.port}"
            # Do not echo path segments either: deployments occasionally put
            # opaque gateway tokens in a URL path rather than a query string.
            return urlunsplit((parsed.scheme, netloc, "", "", ""))
    except Exception:
        pass
    return "<configured>"


def _safe_model(model: str | None) -> str:
    if not model:
        return "<unset>"
    # Model IDs are normally harmless, but a profile can be generated from a
    # secret manager.  Keep all values out of terminal/JSON summaries.
    return "<configured>"


def _api_url(endpoint: str, *, operation: str) -> str:
    endpoint = endpoint.rstrip("/")
    lower = endpoint.lower()
    if operation == "chat" and (lower.endswith("/chat/completions") or lower.endswith("/completions")):
        return endpoint
    if operation == "health" and lower.endswith("/health"):
        return endpoint
    if operation == "health":
        root = endpoint[:-3] if lower.endswith("/v1") else endpoint
        return f"{root}/health"
    if lower.endswith("/v1"):
        return f"{endpoint}/chat/completions"
    return f"{endpoint}/v1/chat/completions"


def _validate_target(spec: ComponentSpec, target: TargetConfig, *, live: bool, allow_cloud: bool) -> list[str]:
    errors: list[str] = []
    if live:
        if not target.endpoint:
            errors.append("endpoint is not configured")
        elif urlsplit(target.endpoint).scheme not in {"http", "https"}:
            errors.append("endpoint must use http or https")
        if not target.model:
            errors.append("model is not configured")
        if spec.vision and not target.image_path:
            errors.append("image path is not configured")
        if spec.vision and target.image_path:
            # Existence is checked without exposing file contents or data.
            try:
                image = Path(target.image_path)
                if not image.is_file():
                    errors.append("image file is not available")
            except OSError:
                errors.append("image file is not available")
        if spec.cloud and not allow_cloud:
            errors.append("cloud checks require --allow-cloud")
        if spec.cloud and not target.api_key:
            errors.append("API key is not configured")
    return errors


def _read_image_data(path: str) -> tuple[str, int]:
    """Read an image for a vision request without ever returning it to output."""

    image = Path(path)
    try:
        size = image.stat().st_size
        if size <= 0 or size > 20 * 1024 * 1024:
            raise LiveConfigError("image file must be between 1 byte and 20 MiB")
        data = image.read_bytes()
    except LiveConfigError:
        raise
    except OSError as exc:
        raise LiveConfigError("image file could not be read") from exc
    suffix = image.suffix.lower()
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}.get(
        suffix, "image/png"
    )
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}", size


def _execute_live(spec: ComponentSpec, target: TargetConfig, message: str) -> tuple[bool, str]:
    """Perform one already-running endpoint check.

    This function is only called after argument parsing and target validation
    have established explicit ``--live`` intent.  It never launches a runtime.
    """

    try:
        import requests  # type: ignore[import-not-found]
    except ImportError as exc:
        raise LiveConfigError("requests is required for --live checks") from exc

    headers = {"Accept": "application/json"}
    if target.api_key:
        headers["Authorization"] = "Bearer " + target.api_key
    if spec.health_only:
        url = _api_url(target.endpoint or "", operation="health")
        response = requests.get(url, headers=headers, timeout=target.timeout)
        status = int(getattr(response, "status_code", 0) or 0)
        if status < 200 or status >= 300:
            return False, f"health endpoint returned HTTP {status}"
        return True, "health endpoint reachable"

    url = _api_url(target.endpoint or "", operation="chat")
    if spec.vision:
        data_uri, _size = _read_image_data(target.image_path or "")
        content: Any = [
            {"type": "text", "text": message},
            {"type": "image_url", "image_url": {"url": data_uri}},
        ]
    else:
        content = message
    payload = {
        "model": target.model,
        "messages": [{"role": "user", "content": content}],
        "stream": False,
    }
    response = requests.post(url, json=payload, headers=headers, timeout=target.timeout)
    status = int(getattr(response, "status_code", 0) or 0)
    if status < 200 or status >= 300:
        return False, f"chat endpoint returned HTTP {status}"
    # Decode only enough to distinguish an empty/error-shaped response.  The
    # response body is never printed (it may contain user text or credentials).
    try:
        body = response.json()
    except Exception:
        body = None
    if isinstance(body, Mapping):
        if body.get("error"):
            return False, "provider returned an error response"
        if body.get("choices") or body.get("content") or body.get("output") or body.get("text"):
            return True, "chat response received"
    # A successful HTTP status is still a useful smoke result for gateways
    # that intentionally return an empty body.
    return True, "chat endpoint returned HTTP success"


def _result(component: str, layer: str, status: str, detail: str, started: float | None = None) -> CheckResult:
    elapsed = None if started is None else (time.perf_counter() - started) * 1000.0
    return CheckResult(component=component, layer=layer, status=status, detail=detail, elapsed_ms=elapsed)


def _run(args: argparse.Namespace) -> tuple[list[CheckResult], int]:
    live = bool(args.live)
    fake = bool(args.fake)
    mode = "live" if live else "fake" if fake else "dry-run"
    components = parse_components(args.component)

    results: list[CheckResult] = []
    profile: Mapping[str, Any]
    profile_path: Path | None
    try:
        profile, profile_path = _find_profile(args.profile, required=live)
    except LiveConfigError as exc:
        results.append(_result("profile", "config", "FAIL", str(exc)))
        return results, 2

    profile_note = "not configured (safe defaults)" if profile_path is None else "loaded"
    results.append(_result("profile", "config", "PASS", f"{profile_note}; mode={mode}"))

    # Attach the profile path privately for relative fixture resolution.  A
    # shallow copy avoids mutating a caller's mapping while keeping YAML/JSON
    # parsing independent from the resolver's display-safe fields.
    if profile_path is not None:
        profile = dict(profile)
        profile["_path"] = str(profile_path)

    for component in components:
        spec = _SPECS[component]
        started = time.perf_counter()
        try:
            target = _resolve_target(profile, component, cli_image=args.image)
        except LiveConfigError as exc:
            results.append(_result(component, "preflight", "FAIL", str(exc), started))
            continue
        errors = _validate_target(spec, target, live=live, allow_cloud=bool(args.allow_cloud))
        if errors:
            results.append(_result(component, "preflight", "FAIL", "; ".join(errors), started))
            continue
        if not live:
            if fake:
                detail = "offline fake passed; network/model startup disabled"
            else:
                detail = (
                    f"would check {_safe_endpoint(target.endpoint)}"
                    f" model={_safe_model(target.model)} timeout={target.timeout:g}s"
                )
            results.append(_result(component, "component", "PASS", detail, started))
            continue
        try:
            ok, detail = _execute_live(spec, target, args.message)
        except LiveConfigError as exc:
            results.append(_result(component, "component", "FAIL", str(exc), started))
        except TimeoutError:
            results.append(_result(component, "component", "FAIL", "request timed out", started))
        except Exception as exc:
            # Exception text can include an Authorization header or URL query;
            # expose only a stable class-level reason.
            name = type(exc).__name__.lower()
            reason = "request failed"
            if "timeout" in name:
                reason = "request timed out"
            elif "connection" in name:
                reason = "endpoint unavailable"
            results.append(_result(component, "component", "FAIL", reason, started))
        else:
            results.append(_result(component, "component", "PASS" if ok else "FAIL", detail, started))

    counts = Counter(result.status for result in results)
    if counts.get("FAIL"):
        # Configuration/profile failures are distinguished from provider
        # failures for automation while preserving a simple non-zero contract.
        code = 2 if any(result.layer in {"config", "preflight"} and result.status == "FAIL" for result in results) else 1
    else:
        code = 0
    return results, code


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="live_verify",
        description=(
            "Explicit Oratrice live checks. Default mode is an offline dry-run; "
            "no model is started and no network is used unless --live is supplied."
        ),
        epilog=(
            "Examples: python scripts/live_verify.py --dry-run; "
            "python scripts/live_verify.py --fake --component core-text; "
            "python scripts/live_verify.py --live --component gateway-gpt"
        ),
    )
    parser.add_argument(
        "--component",
        "--components",
        "-c",
        action="append",
        help="component(s), repeat or comma-separate: " + ", ".join(COMPONENTS),
    )
    parser.add_argument("--profile", help="JSON/YAML live profile path (or ORATRICE_LIVE_PROFILE)")
    parser.add_argument("--live", "--run-live", action="store_true", help="perform real HTTP checks (explicit opt-in)")
    parser.add_argument("--dry-run", action="store_true", help="print the planned checks without reading endpoints (default)")
    parser.add_argument("--fake", "--offline-fake", action="store_true", help="run deterministic offline fake checks")
    parser.add_argument("--allow-cloud", action="store_true", help="allow the deepseek-cloud check to use a cloud endpoint")
    parser.add_argument("--image", help="vision fixture path (qwen-vision; never printed or uploaded in dry-run/fake)")
    parser.add_argument("--message", default="Oratrice live verification", help="non-sensitive smoke prompt")
    parser.add_argument("--json", action="store_true", help="emit a machine-readable redacted summary")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.live and (args.dry_run or args.fake):
        parser.error("--live cannot be combined with --dry-run or --fake")
    if args.dry_run and args.fake:
        parser.error("--dry-run cannot be combined with --fake")
    try:
        results, code = _run(args)
    except LiveConfigError as exc:
        # Defensive boundary for parser/resolver errors.  Keep this message
        # free of values read from profile secrets.
        results = [_result("profile", "config", "FAIL", str(exc))]
        code = 2

    if args.json:
        payload = {
            "mode": "live" if args.live else "fake" if args.fake else "dry-run",
            "results": [result.as_dict() for result in results],
            "summary": dict(Counter(result.status for result in results)),
            "exit_code": code,
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print("Oratrice live verification (explicit mode; no automatic model startup)")
        current_layer = None
        for result in results:
            if result.layer != current_layer:
                current_layer = result.layer
                print(f"[{current_layer}]")
            suffix = "" if result.elapsed_ms is None else f" ({result.elapsed_ms:.1f} ms)"
            print(f"  {result.status:<4} {result.component}: {result.detail}{suffix}")
        counts = Counter(result.status for result in results)
        print(
            "SUMMARY "
            + " ".join(f"{name}={counts.get(name, 0)}" for name in ("PASS", "FAIL", "SKIP"))
            + f" exit={code}"
        )
    return code


if __name__ == "__main__":  # pragma: no cover - exercised via CLI
    raise SystemExit(main())
