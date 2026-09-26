"""Single, offline M5 release-readiness gate.

This file is intentionally independent from the M1--M4 test paths.  It is a
small composition check: configuration and launcher contracts are inspected
without starting a process, while the HTTP checks use an injected facade and
FastAPI's in-process ``TestClient``.  A real socket, subprocess, model, or
provider call is a test failure, not a reason to retry against a live stack.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path
import os
import socket
import subprocess
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from core.ai_service import CoreFacade
from core.configuration import ConfigurationLoader
from core.errors import CoreRoutingError
from core.observability import HealthReport
from launcher.cli import CONFIG_PATH_ENV, GATEWAY_KEY_ENV, run
from launcher.plan import LaunchPlan
from oratrice_api import create_api
from oratrice_api.errors import status_for_error
from providers import ChatResponse
from router import RouteDecision, RouterTransportError


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "config" / "profiles" / "live.yaml"
FORBIDDEN_IMPORTS = {
    "httpx",
    "litellm",
    "requests",
    "socket",
    "subprocess",
    "urllib.request",
}


def _module_imports(path: Path) -> set[str]:
    # A contributor-edited policy module may carry a UTF-8 BOM; AST inspection
    # should validate its imports rather than fail on that harmless marker.
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def _load_live(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(GATEWAY_KEY_ENV, "m5-offline-placeholder")
    return ConfigurationLoader(PROFILE).load()


def test_m5_static_boundaries_and_live_entrypoint():
    paths = [
        ROOT / "cli.py",
        ROOT / "main.py",
        *(ROOT / "oratrice_api").glob("*.py"),
        ROOT / "core" / "ai_service.py",
        *(ROOT / "router").glob("*.py"),
        *(ROOT / "entities").glob("*.py"),
    ]
    for path in paths:
        imports = _module_imports(path)
        if path.parent.name in {"oratrice_api", "router", "entities"} or path.name in {
            "cli.py",
            "main.py",
            "ai_service.py",
        }:
            assert not any(
                item == forbidden or item.startswith(forbidden + ".")
                for item in imports
                for forbidden in FORBIDDEN_IMPORTS
            ), f"transport/process import leaked into {path}"

    main_tree = ast.parse(
        (ROOT / "oratrice_api" / "main.py").read_text(encoding="utf-8-sig")
    )
    app_assignments = [
        node
        for node in ast.walk(main_tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "app" for target in node.targets)
    ]
    assert app_assignments, "oratrice_api.main must export app"
    app_call = app_assignments[-1].value
    assert isinstance(app_call, ast.Call)
    assert isinstance(app_call.func, ast.Name) and app_call.func.id == "create_api"
    assert not any(
        isinstance(node, ast.Name) and node.id == "build_application"
        for node in ast.walk(main_tree)
    ), "entrypoint must defer Application construction to FastAPI lifespan"

    runtime_args = tuple(
        _load_live_for_static().runtimes["runtime.core_api"].args
    )
    assert runtime_args[:3] == ("-m", "uvicorn", "oratrice_api.main:app")


def _load_live_for_static():
    # Static configuration loading is side-effect free; the profile's
    # LiteLLM key reference is expanded only for this in-memory check.
    old = os.environ.get(GATEWAY_KEY_ENV)
    os.environ[GATEWAY_KEY_ENV] = "m5-static-placeholder"
    try:
        return ConfigurationLoader(PROFILE).load()
    finally:
        if old is None:
            os.environ.pop(GATEWAY_KEY_ENV, None)
        else:
            os.environ[GATEWAY_KEY_ENV] = old


def test_m5_config_launcher_candidates_and_secret_boundary(monkeypatch):
    configuration = _load_live(monkeypatch)
    plan = LaunchPlan.from_configuration(configuration)

    assert [target.id for target in plan.targets] == [
        "gpt_oss",
        "gemma_router",
        "litellm_gateway",
        "core_api",
    ]
    assert plan.attempt_limit == 3
    assert plan.optional_targets[0].id == "qwen_vl"
    assert plan.optional_targets[0].before == "litellm_gateway"

    core_api = plan.targets[-1]
    assert core_api.runtime_id == "runtime.core_api"
    assert core_api.timeout == 60
    assert core_api.health_endpoint == "http://127.0.0.1:8000/health"

    strategy = configuration.defaults["router"]["strategy"]
    candidates = strategy["candidates"]
    assert {item["model"] for item in candidates} >= {
        "gpt_oss",
        "qwen_vl",
        "deepseek_reasoner",
    }
    assert all(item["provider"] in configuration.providers for item in candidates)
    cloud = next(item for item in candidates if item["model"] == "deepseek_reasoner")
    assert cloud["requires_cloud_opt_in"] is True
    assert cloud["priority"] > 0
    assert next(item for item in candidates if item["model"] == "gpt_oss")["priority"] < 0

    raw = configuration.to_dict()
    assert "m5-static-placeholder" not in repr(raw)
    assert "DEEPSEEK_API_KEY" not in repr(raw)


def test_m5_alias_resolves_to_canonical_runtime_without_starting_process(monkeypatch):
    configuration = _load_live(monkeypatch)

    class RuntimeProbe:
        def __init__(self):
            self.calls: list[tuple[str, str]] = []

        def status_model(self, model_id):
            self.calls.append(("status", model_id))
            return "stopped"

        def start_model(self, model_id):
            self.calls.append(("start", model_id))

    manager = RuntimeProbe()
    facade = CoreFacade(configuration=configuration, manager=manager, auto_start=True)
    facade._ensure_runtime("gpt_oss", "m5-runtime")

    assert manager.calls == [
        ("status", "model.gpt_oss"),
        ("start", "model.gpt_oss"),
    ]


def test_m5_launcher_profile_env_is_propagated_and_restored(monkeypatch):
    original_key = "original-m5-key"
    original_profile = "original-profile.yaml"
    monkeypatch.setenv(GATEWAY_KEY_ENV, original_key)
    monkeypatch.setenv(CONFIG_PATH_ENV, original_profile)
    environment = {
        GATEWAY_KEY_ENV: original_key,
        CONFIG_PATH_ENV: original_profile,
    }
    observed: list[dict[str, str]] = []

    class DryRunOrchestrator:
        def __init__(self, configuration, *, env):
            observed.append(dict(env))

        def start(self, **kwargs):
            assert kwargs["dry_run"] is True
            return type(
                "Result",
                (),
                {"status": "PASS", "ok": True, "outcomes": (), "ui_status": "NOT_REQUESTED"},
            )()

        def stop(self):
            raise AssertionError("dry-run must not stop an owned process")

    assert run(
        ["--profile", str(PROFILE), "--dry-run", "--no-browser"],
        orchestrator_factory=DryRunOrchestrator,
        environ=environment,
        output=lambda _: None,
    ) == 0
    assert observed and observed[0][CONFIG_PATH_ENV] == str(PROFILE.resolve())
    assert environment == {
        GATEWAY_KEY_ENV: original_key,
        CONFIG_PATH_ENV: original_profile,
    }
    assert os.environ[GATEWAY_KEY_ENV] == original_key
    assert os.environ[CONFIG_PATH_ENV] == original_profile


class _FakeFacade:
    def __init__(self):
        self.health_mode = "liveness"
        self.chat_calls: list[dict[str, object]] = []
        self.route_calls: list[dict[str, object]] = []

    def chat(self, **kwargs):
        self.chat_calls.append(dict(kwargs))
        return ChatResponse(
            content="offline m5",
            model=kwargs.get("model_id"),
            provider="provider.fake",
            usage={"total_tokens": 1},
            raw={"prompt": "hidden"},
        )

    def route(self, **kwargs):
        self.route_calls.append(dict(kwargs))
        if kwargs.get("metadata", {}).get("transport_failure"):
            raise CoreRoutingError(
                "router transport unavailable",
                cause=RouterTransportError("offline transport"),
            )
        return RouteDecision(
            model=kwargs.get("model_id") or "model.fake",
            provider="provider.fake",
            task_type="chat",
            complexity="low",
            capabilities=("chat",),
            reason="offline",
        )

    def health(self, **kwargs):
        assert kwargs["include_configured"] is False
        if self.health_mode == "active-unhealthy":
            return HealthReport(
                status="unhealthy",
                components={"providers": {"provider.fake": {"status": "unhealthy", "healthy": False}}},
                request_id=kwargs["request_id"],
            )
        return HealthReport(status="unknown", components={}, request_id=kwargs["request_id"])


class _FakeApplication:
    def __init__(self, facade):
        self.facade = facade
        self.close_calls = 0

    def close(self):
        self.close_calls += 1


def test_m5_api_in_process_liveness_routing_mapping_and_no_side_effects(monkeypatch):
    calls: list[str] = []

    def forbidden_connection(*args, **kwargs):
        calls.append("socket")
        raise AssertionError("M5 API gate attempted an external socket connection")

    def forbidden_process(*args, **kwargs):
        calls.append("process")
        raise AssertionError("M5 API gate attempted a subprocess")

    facade = _FakeFacade()
    application = _FakeApplication(facade)
    with TestClient(
        create_api(application=application), raise_server_exceptions=False
    ) as client:
        # Starlette/AnyIO creates a local self-pipe while entering TestClient
        # on Windows.  Guard the external connection helper only after that
        # portal exists; replacing ``socket.socket`` would break the client
        # transport itself and is not evidence of an application side effect.
        monkeypatch.setattr(socket, "create_connection", forbidden_connection)
        monkeypatch.setattr(subprocess, "Popen", forbidden_process)
        chat = client.post("/chat", json={"message": "hello", "model": "gpt_oss"})
        assert chat.status_code == 200
        assert chat.json()["content"] == "offline m5"
        assert "raw" not in chat.json()
        assert "prompt" not in chat.text

        route = client.post("/route", json={"message": "hello", "model": "gpt_oss"})
        assert route.status_code == 200
        request_id = route.json()["request_id"]
        UUID(request_id)
        assert facade.route_calls[-1]["request_id"] == request_id
        assert "content" not in route.json()

        liveness = client.get("/health")
        assert liveness.status_code == 200
        assert liveness.json()["status"] == "healthy"
        assert liveness.json()["healthy"] is True
        assert liveness.json()["details"]["mode"] == "liveness"

        facade.health_mode = "active-unhealthy"
        unhealthy = client.get("/health")
        assert unhealthy.status_code == 200
        assert unhealthy.json()["status"] == "unhealthy"
        assert unhealthy.json()["healthy"] is False

        transport = client.post(
            "/route",
            json={
                "message": "hello",
                "metadata": {"transport_failure": True},
            },
        )
        assert transport.status_code == 503
        assert transport.json()["error"]["code"] == "routing_error"
        assert "cause" not in transport.json()["error"]

        invalid = client.post("/chat", json={"message": "hello", "extra": "secret"})
        assert invalid.status_code == 422
        assert invalid.json() == {
            "error": {"code": "validation_error", "message": "invalid request"}
        }

    assert application.close_calls == 0
    assert calls == []
    assert status_for_error(
        CoreRoutingError("transport", cause=RouterTransportError("offline"))
    ) == 503


__all__ = []
