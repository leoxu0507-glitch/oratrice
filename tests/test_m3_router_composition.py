"""Offline M3 composition contracts for the declarative router strategy.

The test builds the application graph with an injected routing client and a
fake runtime controller.  It inspects the policy catalogue and feeds strict
fake decisions through the router; no model, provider, gateway, socket, or
subprocess is started.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.application import build_application
from core.configuration import ConfigurationLoader
from router import GemmaRouterProvider, RouteParseError, RouterRequest
from router.policy import RoutingPolicy


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LIVE_PROFILE = PROJECT_ROOT / "config" / "profiles" / "live.yaml"


class FakeRoutingClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.response: dict[str, object] | None = None

    def complete(self, **kwargs):
        self.calls.append(dict(kwargs))
        if self.response is None:
            raise AssertionError("a fake route decision must be configured")
        return dict(self.response)


class FakeProviderRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def create(self, provider_type, config):
        self.calls.append((provider_type, dict(config)))
        raise AssertionError("provider construction is outside this composition test")


class FakeRuntimeManager:
    def __init__(self) -> None:
        self.stop_all_calls = 0

    def stop_all(self):
        self.stop_all_calls += 1
        return {}


def _application(monkeypatch):
    monkeypatch.setenv("ORATRICE_LITELLM_MASTER_KEY", "offline-m3-master")
    configuration = ConfigurationLoader().load(LIVE_PROFILE)
    client = FakeRoutingClient()
    registry = FakeProviderRegistry()
    runtime = FakeRuntimeManager()
    app = build_application(
        configuration=configuration,
        provider_registry=registry,
        provider_instances={"provider.gemma_router": client},
        runtime_manager=runtime,
        auto_start=False,
    )
    return app, client, registry, runtime


def test_m3_strategy_is_injected_without_constructing_or_calling_models(monkeypatch):
    app, client, registry, runtime = _application(monkeypatch)
    try:
        assert isinstance(app.router, GemmaRouterProvider)
        assert isinstance(app.router.decision_policy, RoutingPolicy)
        assert client.calls == []
        assert registry.calls == []

        # Every strategy candidate is part of the adapter's global schema
        # allow-list, including the cloud candidate.  This is only a parser
        # constraint; eligibility remains request/policy dependent.
        assert set(app.router.allowed_models) >= {
            "gpt_oss",
            "qwen_vl",
            "deepseek_reasoner",
        }
        assert set(app.router.allowed_providers) >= {
            "provider.litellm_gateway",
            "provider.litellm_cloud",
        }
    finally:
        app.close()
    assert runtime.stop_all_calls == 1


def test_m3_policy_catalog_hides_cloud_until_metadata_opt_in(monkeypatch):
    app, client, registry, runtime = _application(monkeypatch)
    try:
        normal = app.router.request_payload(RouterRequest("hello"))
        normal_catalog = normal["candidate_catalog"]
        assert all(item["provider"] != "provider.litellm_cloud" for item in normal_catalog)

        opted_in = app.router.request_payload(
            RouterRequest("hello", metadata={"allow_cloud": True})
        )
        opted_catalog = opted_in["candidate_catalog"]
        assert any(
            item["model"] == "deepseek_reasoner"
            and item["provider"] == "provider.litellm_cloud"
            for item in opted_catalog
        )

        # Assert the actual prompt envelope remains deterministic JSON and no
        # fake transport call happened while composing or inspecting it.
        prompt = app.router.build_messages(RouterRequest("hello"))[-1]["content"]
        assert isinstance(json.loads(prompt)["candidate_catalog"], list)
        assert client.calls == []
        assert registry.calls == []
    finally:
        app.close()
    assert runtime.stop_all_calls == 1


def _decision(model, provider, task_type, complexity, capabilities, **flags):
    return {
        "model": model,
        "provider": provider,
        "task_type": task_type,
        "complexity": complexity,
        "capabilities": capabilities,
        "requires_vision": flags.get("requires_vision", False),
        "requires_network": flags.get("requires_network", False),
        "requires_tools": flags.get("requires_tools", False),
        "reason": "offline M3 policy fixture",
        "confidence": 1.0,
    }


def test_m3_fake_decisions_follow_configured_task_capability_and_cloud_policy(monkeypatch):
    app, client, registry, runtime = _application(monkeypatch)
    try:
        client.response = _decision(
            "gpt_oss", "provider.litellm_gateway", "chat", "low", ["chat"]
        )
        assert app.router.route(RouterRequest("hello")).model == "gpt_oss"

        client.response = _decision(
            "qwen_vl",
            "provider.litellm_gateway",
            "vision",
            "medium",
            ["vision"],
            requires_vision=True,
        )
        assert app.router.route(
            RouterRequest("describe this image", requires_vision=True)
        ).model == "qwen_vl"

        client.response = _decision(
            "deepseek_reasoner",
            "provider.litellm_cloud",
            "reasoning",
            "high",
            ["reasoning"],
        )
        cloud_request = RouterRequest(
            "solve a difficult proof", metadata={"allow_cloud": True}
        )
        assert app.router.route(cloud_request).model == "deepseek_reasoner"

        with pytest.raises(RouteParseError):
            app.router.route(RouterRequest("solve a difficult proof"))

        assert len(client.calls) == 4
        assert registry.calls == []
    finally:
        app.close()
    assert runtime.stop_all_calls == 1
