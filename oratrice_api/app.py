"""In-process FastAPI boundary for the Oratrice core facade.

Creating the ASGI application only registers routes and handlers.  The
composition factory is invoked from the FastAPI lifespan, with
``auto_start=False``, so importing or constructing this module cannot start a
runtime, load model weights, or make a provider request.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import inspect
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from core.application import build_application
from core.errors import CoreConfigurationError, CoreError

from .contracts import (
    ChatRequest,
    RouteRequest,
    health_envelope,
    serialise_chat_response,
    serialise_health,
    serialise_route_decision,
)
from .errors import error_payload, status_for_error, validation_payload


ApplicationFactory = Callable[..., Any]
ReadinessChecker = Callable[..., Any]


_HEALTHY_STATUSES = frozenset({"ok", "healthy", "ready", "up", "running"})
_STATE_KEYS = frozenset({"status", "state", "healthy", "ok", "is_healthy"})
_COMPONENT_META_KEYS = frozenset(
    {"component", "component_id", "id", "lazy", "details"}
)
_DECLARATION_KEYS = (
    "required",
    "required_components",
    "required_dependencies",
    "optional",
    "optional_components",
    "optional_dependencies",
)

# The browser UI is shipped with the repository and served by the same API
# origin.  Keeping this path relative to the package makes the launcher and
# an in-process TestClient use the same static assets without a second server
# or a build-time dependency.
_WEB_UI_ROOT = Path(__file__).resolve().parents[1] / "frontends" / "web"


def _now_iso() -> str:
    """Return an explicit UTC timestamp for probe envelopes."""

    return datetime.now(timezone.utc).isoformat()


def _object_mapping(value: Any) -> dict[str, Any]:
    """Read a report-like value without invoking arbitrary serializers."""

    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        result = to_dict()
        if isinstance(result, Mapping):
            return dict(result)
    values = getattr(value, "__dict__", None)
    return dict(values) if isinstance(values, Mapping) else {}


def _component_entries(
    value: Any,
    *,
    path: tuple[str, ...] = (),
    inherited_optional: bool = False,
):
    """Yield ``(name, value, optional)`` leaves from nested health data."""

    if isinstance(value, Mapping):
        optional = inherited_optional or value.get("optional") is True or value.get("required") is False
        has_state = any(key in value for key in _STATE_KEYS)
        if has_state:
            yield ".".join(path) or "component", value, optional
            return
        children = [
            (str(key), child)
            for key, child in value.items()
            if str(key) not in _COMPONENT_META_KEYS
        ]
        if not children:
            if path:
                yield ".".join(path), value, optional
            return
        for key, child in children:
            yield from _component_entries(
                child,
                path=(*path, key),
                inherited_optional=optional,
            )
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            yield from _component_entries(
                child,
                path=(*path, str(index)),
                inherited_optional=inherited_optional,
            )
        return
    if path:
        yield ".".join(path), value, inherited_optional


def _component_healthy(value: Any) -> bool:
    """Interpret one leaf using the provider/runtime health vocabulary."""

    if isinstance(value, Mapping):
        for key in ("healthy", "ok", "is_healthy"):
            if key in value and isinstance(value[key], bool):
                return value[key]
        status = value.get("status", value.get("state"))
    else:
        status = getattr(value, "status", getattr(value, "state", value))
        explicit = getattr(value, "healthy", getattr(value, "ok", None))
        if isinstance(explicit, bool):
            return explicit
    if isinstance(status, bool):
        return status
    return str(getattr(status, "value", status)).strip().lower() in _HEALTHY_STATUSES


def _declaration_names(value: Any, *, prefix: tuple[str, ...] = ()) -> set[str]:
    """Normalise required/optional declarations into comparable component IDs."""

    names: set[str] = set()
    if isinstance(value, str):
        text = value.strip()
        if text:
            names.add(text)
        return names
    if isinstance(value, (list, tuple, set, frozenset)):
        for child in value:
            names.update(_declaration_names(child, prefix=prefix))
        return names
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key).strip()
            if not key_text:
                continue
            path = (*prefix, key_text)
            if isinstance(child, (Mapping, list, tuple, set, frozenset)):
                names.add(".".join(path))
                names.update(_declaration_names(child, prefix=path))
            elif isinstance(child, bool):
                names.add(".".join(path))
        return names
    return names


def _find_declarations(value: Any) -> tuple[set[str], set[str], bool]:
    """Find explicit readiness declarations in checker/report metadata."""

    if not isinstance(value, Mapping):
        return set(), set(), False
    required: set[str] = set()
    optional: set[str] = set()
    found = False
    for key, child in value.items():
        key_text = str(key).lower()
        if key_text in {"required", "required_components", "required_dependencies"}:
            required.update(_declaration_names(child))
            found = True
        elif key_text in {"optional", "optional_components", "optional_dependencies"}:
            optional.update(_declaration_names(child))
            found = True
        elif key_text in {"readiness", "readiness_checks", "classification", "dependencies"}:
            nested_required, nested_optional, nested_found = _find_declarations(child)
            required.update(nested_required)
            optional.update(nested_optional)
            found = found or nested_found
    return required, optional, found


def _component_matches(name: str, declaration: str) -> bool:
    """Match both grouped (``providers.foo``) and flat (``foo``) IDs."""

    left = str(name).strip()
    right = str(declaration).strip()
    if not left or not right:
        return False
    if left == right or left.startswith(right + "."):
        return True
    return left.rsplit(".", 1)[-1] == right.rsplit(".", 1)[-1]


def _readiness_classification(
    report: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> tuple[list[tuple[str, Any, bool]], bool]:
    """Classify report leaves and return ``(entries, has_components)``."""

    source = _object_mapping(report)
    components = source.get("components", {})
    leaves = list(_component_entries(components)) if isinstance(components, (Mapping, list, tuple)) else []
    report_details = source.get("details")
    required: set[str] = set()
    optional: set[str] = set()
    declared = False
    for candidate in (metadata, report_details):
        item_required, item_optional, item_declared = _find_declarations(candidate)
        required.update(item_required)
        optional.update(item_optional)
        declared = declared or item_declared

    classified: list[tuple[str, Any, bool]] = []
    seen: set[str] = set()
    for name, value, marked_optional in leaves:
        if any(_component_matches(name, item) for item in required):
            is_optional = False
        elif any(_component_matches(name, item) for item in optional):
            is_optional = True
        else:
            # Explicit declarations are intentionally conservative: an item
            # omitted from an optional list remains required rather than being
            # silently downgraded.
            is_optional = marked_optional
        classified.append((name, value, is_optional))
        seen.add(name)

    # A declaration for a missing required dependency is itself a failed
    # readiness check; retaining a synthetic unknown leaf makes that failure
    # visible to the same classifier as unhealthy/unknown health data.
    for name in required:
        if not any(_component_matches(existing, name) for existing in seen):
            classified.append((name, None, False))
    for name in optional:
        if not any(_component_matches(existing, name) for existing in seen):
            classified.append((name, None, True))
    return classified, bool(leaves)


def _checker_callable(value: Any) -> Callable[..., Any] | None:
    if callable(value):
        return value
    for name in ("check_readiness", "readiness", "ready", "health", "check_health", "check"):
        candidate = getattr(value, name, None)
        if callable(candidate):
            return candidate
    return None


def _invoke_checker(
    checker: Callable[..., Any],
    *,
    request: Request,
    application: Any,
    facade: Any,
    request_id: str,
) -> Any:
    """Invoke an injected checker without imposing one callback signature."""

    values = {
        "request": request,
        "application": application,
        "app": application,
        "facade": facade,
        "core": facade,
        "service": facade,
        "request_id": request_id,
        "correlation_id": request_id,
    }
    try:
        signature = inspect.signature(checker)
    except (TypeError, ValueError):
        return checker(application)
    parameters = list(signature.parameters.values())
    accepts_var_kw = any(item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters)
    kwargs = {name: values[name] for name in values if name in signature.parameters}
    if accepts_var_kw:
        kwargs = dict(values)
    required_positional = [
        item
        for item in parameters
        if item.default is inspect.Parameter.empty
        and item.kind in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
        and item.name not in kwargs
    ]
    if required_positional:
        return checker(application, **kwargs) if len(required_positional) == 1 else checker(application, facade, **kwargs)
    return checker(**kwargs)


def _invoke_health(facade: Any, request_id: str) -> Any:
    """Call facade health in non-constructing configured-report mode."""

    health = getattr(facade, "health", None)
    if not callable(health):
        raise CoreConfigurationError("application has no health provider")
    try:
        signature = inspect.signature(health)
    except (TypeError, ValueError):
        return health(request_id=request_id, include_configured=True)
    parameters = signature.parameters
    kwargs: dict[str, Any] = {}
    if "request_id" in parameters or any(item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters.values()):
        kwargs["request_id"] = request_id
    if "include_configured" in parameters or any(item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters.values()):
        kwargs["include_configured"] = True
    return health(**kwargs)


def _coerce_checker_result(value: Any) -> tuple[Any, Mapping[str, Any] | None]:
    """Accept a report directly or a report plus readiness metadata."""

    if isinstance(value, tuple) and len(value) == 2:
        report, metadata = value
        return report, metadata if isinstance(metadata, Mapping) else None
    source = _object_mapping(value)
    if isinstance(source, Mapping) and "report" in source:
        report = source.get("report")
        metadata = {key: child for key, child in source.items() if key != "report"}
        return report, metadata
    if isinstance(source, Mapping):
        _, _, declared = _find_declarations(source)
        if declared:
            metadata = {key: child for key, child in source.items() if str(key).lower() in _DECLARATION_KEYS}
            return value, metadata
    return value, None


def _ready_payload(
    report: Any,
    *,
    request_id: str,
    metadata: Mapping[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Map a health report to the required/degraded/not-ready contract."""

    safe = serialise_health(report, request_id=request_id)
    entries, has_components = _readiness_classification(report, metadata=metadata)
    required_entries = [item for item in entries if not item[2]]
    optional_entries = [item for item in entries if item[2]]
    # An explicit optional-only graph has no blocking dependencies; the
    # empty *graph* case is still handled separately below as not-ready.
    required_ok = all(_component_healthy(value) for _, value, _ in required_entries)
    # No component graph is an explicit not-ready state.  It avoids declaring
    # a process ready merely because no dependency has been observed yet.
    if not has_components or not required_ok:
        status, healthy, http_status = "not_ready", False, 503
    else:
        optional_ok = all(_component_healthy(value) for _, value, _ in optional_entries)
        status, healthy, http_status = ("ready", True, 200) if optional_ok else ("degraded", True, 200)
    details = safe.get("details")
    details = dict(details) if isinstance(details, Mapping) else {}
    details["mode"] = "readiness"
    payload = health_envelope(
        status=status,
        healthy=healthy,
        components=safe.get("components", {}),
        request_id=request_id,
        checked_at=safe.get("checked_at") or _now_iso(),
        details=details,
    )
    return http_status, payload


def _close_application(application: Any) -> None:
    close = getattr(application, "close", None)
    if not callable(close):
        close = getattr(application, "shutdown", None)
    if callable(close):
        close()


def _application_from_request(request: Request) -> Any:
    application = getattr(request.app.state, "application", None)
    if application is None:
        raise CoreConfigurationError("application is not initialized")
    return application


def _facade(application: Any) -> Any:
    facade = getattr(application, "facade", None)
    if facade is None:
        # A directly injected facade is useful for tiny in-process tests.
        facade = application
    if facade is None:
        raise CoreConfigurationError("application has no core facade")
    return facade


def _has_active_health_components(report: Mapping[str, Any]) -> bool:
    """Return whether a health report contains a probed component.

    ``include_configured=False`` deliberately omits lazy/configured resources
    from the API probe.  A report with only ``unknown`` placeholders therefore
    represents an idle application and can be used as a liveness response;
    an explicitly unhealthy component, however, remains a real dependency
    failure and must not be hidden.
    """

    components = report.get("components", {})
    if not isinstance(components, Mapping):
        return False

    def active(value: Any) -> bool:
        if isinstance(value, Mapping):
            status = str(value.get("status", "")).strip().lower()
            if status and status not in {"unknown", "inactive", "not_configured"}:
                return True
            if value.get("healthy") is True:
                return True
            return any(active(child) for child in value.values())
        if isinstance(value, (list, tuple)):
            return any(active(child) for child in value)
        return False

    return any(active(value) for value in components.values())


def create_api(
    application: Any = None,
    application_factory: ApplicationFactory = build_application,
    config_path: str | None = None,
    readiness_checker: ReadinessChecker | None = None,
    readiness_provider: Any = None,
) -> FastAPI:
    """Create the Oratrice API without constructing an application.

    An injected ``application`` is considered externally owned and is never
    closed by the API lifespan.  When no application is injected, the factory
    is called lazily on lifespan entry with ``auto_start=False`` and its
    resulting application is closed exactly once on lifespan exit.  A
    ``readiness_checker`` (or the descriptive ``readiness_provider`` alias)
    can supply a precomputed health report/classification for ``/ready``;
    otherwise the existing facade health port is queried in configured-report
    mode, which represents lazy resources as ``unknown`` without constructing
    or starting them.
    """

    state: dict[str, Any] = {
        "application": application,
        "owned": False,
    }

    @asynccontextmanager
    async def lifespan(api: FastAPI):
        if state["application"] is None:
            state["application"] = application_factory(
                config_path=config_path,
                auto_start=False,
            )
            state["owned"] = True
        api.state.application = state["application"]
        try:
            yield
        finally:
            if state["owned"] and state["application"] is not None:
                owned = state["application"]
                # Clear first so a re-entrant shutdown cannot close it twice.
                state["application"] = None
                state["owned"] = False
                api.state.application = None
                _close_application(owned)

    api = FastAPI(
        title="Oratrice API",
        version="1",
        lifespan=lifespan,
    )
    api.state.application = application

    # StaticFiles only registers an ASGI mount; it does not open a socket,
    # construct the application graph, or contact a provider.  The explicit
    # directory check keeps an incomplete source/package from making the core
    # API importable only when the optional UI assets are present.
    if _WEB_UI_ROOT.is_dir():
        api.mount(
            "/ui",
            StaticFiles(directory=str(_WEB_UI_ROOT), html=True),
            name="web-ui",
        )

    @api.exception_handler(RequestValidationError)
    async def request_validation_handler(request: Request, exc: RequestValidationError):
        del request, exc
        return JSONResponse(status_code=422, content=validation_payload())

    @api.exception_handler(CoreError)
    async def core_error_handler(request: Request, exc: CoreError):
        del request
        return JSONResponse(
            status_code=status_for_error(exc),
            content=error_payload(exc),
        )

    @api.exception_handler(Exception)
    async def unknown_error_handler(request: Request, exc: Exception):
        del request
        return JSONResponse(status_code=500, content=error_payload(exc))

    @api.post("/chat")
    def chat(payload: ChatRequest, request: Request):
        application_value = _application_from_request(request)
        facade = _facade(application_value)
        values = payload.model_dump(exclude_none=True)
        model = values.pop("model", None)
        message = values.pop("message")
        try:
            response = facade.chat(model_id=model, message=message, **values)
        except CoreError:
            raise
        except Exception as exc:
            # ServerErrorMiddleware re-raises broad Exception handlers after
            # sending a response in some Starlette versions.  Handling the
            # final unknown case at the endpoint keeps the JSON envelope
            # deterministic for both ASGI servers and TestClient.
            return JSONResponse(status_code=500, content=error_payload(exc))
        return serialise_chat_response(response)

    @api.post("/route")
    def route(payload: RouteRequest, request: Request):
        application_value = _application_from_request(request)
        facade = _facade(application_value)
        request_id = str(uuid4())
        values = payload.model_dump(exclude_none=True)
        message = values.pop("message")
        model = values.pop("model", None)
        try:
            decision = facade.route(
                message=message,
                model_id=model,
                request_id=request_id,
                **values,
            )
        except CoreError:
            raise
        except Exception as exc:
            return JSONResponse(status_code=500, content=error_payload(exc, request_id=request_id))
        return serialise_route_decision(decision, request_id=request_id)

    @api.get("/live")
    def live():
        """Return process liveness without touching application state."""

        request_id = str(uuid4())
        return health_envelope(
            status="live",
            healthy=True,
            components={},
            request_id=request_id,
            checked_at=_now_iso(),
            details={"mode": "liveness"},
        )

    @api.get("/ready")
    def ready(request: Request):
        """Return dependency readiness without creating providers/runtimes."""

        request_id = str(uuid4())
        try:
            application_value = _application_from_request(request)
            facade = _facade(application_value)
            checker_value = readiness_checker or readiness_provider
            if checker_value is None:
                checker_value = getattr(application_value, "readiness_checker", None)
            if checker_value is None:
                checker_value = getattr(application_value, "readiness_provider", None)
            if checker_value is None:
                checker_value = getattr(facade, "readiness_checker", None)
            checker = _checker_callable(checker_value)
            if checker is None:
                if checker_value is None:
                    report = _invoke_health(facade, request_id)
                    metadata = None
                else:
                    # A static HealthReport/mapping is also a valid injected
                    # readiness provider; it is already computed and must not
                    # trigger a facade/provider/runtime call.
                    report, metadata = _coerce_checker_result(checker_value)
            else:
                report, metadata = _coerce_checker_result(
                    _invoke_checker(
                        checker,
                        request=request,
                        application=application_value,
                        facade=facade,
                        request_id=request_id,
                    )
                )
            status_code, payload = _ready_payload(
                report,
                request_id=request_id,
                metadata=metadata,
            )
            return JSONResponse(status_code=status_code, content=payload)
        except CoreError as exc:
            failure = error_payload(exc, request_id=request_id)["error"]
            payload = health_envelope(
                status="not_ready",
                healthy=False,
                components={},
                request_id=request_id,
                checked_at=_now_iso(),
                details={"mode": "readiness", "error": failure},
            )
            return JSONResponse(status_code=503, content=payload)
        except Exception as exc:
            failure = error_payload(exc, request_id=request_id)["error"]
            payload = health_envelope(
                status="not_ready",
                healthy=False,
                components={},
                request_id=request_id,
                checked_at=_now_iso(),
                details={"mode": "readiness", "error": failure},
            )
            return JSONResponse(status_code=503, content=payload)

    @api.get("/health")
    def health(request: Request):
        request_id = str(uuid4())
        try:
            application_value = _application_from_request(request)
            facade = _facade(application_value)
            report = facade.health(request_id=request_id, include_configured=False)
            result = serialise_health(report, request_id=request_id)
            if (
                str(result.get("status", "unknown")).strip().lower() == "unknown"
                and not _has_active_health_components(result)
            ):
                # The API is also a liveness probe.  An idle graph with no
                # active providers/runtimes is alive even though readiness is
                # still unknown; make that distinction explicit to callers.
                result["status"] = "healthy"
                result["healthy"] = True
                details = result.get("details")
                if not isinstance(details, dict):
                    details = {}
                details["mode"] = "liveness"
                result["details"] = details
            return result
        except CoreError as exc:
            # Health is a probe endpoint: dependency failure is represented in
            # its report while the HTTP status remains 200 for load balancers.
            failure = error_payload(exc, request_id=request_id)["error"]
            return {
                "status": "unhealthy",
                "healthy": False,
                "components": {},
                "request_id": request_id,
                "details": {"error": failure},
            }
        except Exception:
            return {
                "status": "unhealthy",
                "healthy": False,
                "components": {},
                "request_id": request_id,
            }

    return api


__all__ = ["create_api"]
