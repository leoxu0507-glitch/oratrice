"""Offline contract tests for the live LiteLLM gateway credential boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.application import build_application
from core.configuration import ConfigurationError, ConfigurationLoader
from providers import LiteLLMGatewayProvider
from providers.registry import ProviderRegistry
from router import RouteDecision, StaticRouter


LIVE_PROFILE = Path(__file__).resolve().parents[1] / "config" / "profiles" / "live.yaml"


class _NoNetworkSession:
    """Session sentinel: construction must not issue HTTP requests."""

    def get(self, *_args, **_kwargs):  # pragma: no cover - a failure is enough
        raise AssertionError("offline credential test attempted an HTTP GET")

    def post(self, *_args, **_kwargs):  # pragma: no cover - a failure is enough
        raise AssertionError("offline credential test attempted an HTTP POST")


def test_live_profile_resolves_gateway_api_key_from_environment(monkeypatch):
    resolved = "offline-test-master-key"
    monkeypatch.setenv("ORATRICE_LITELLM_MASTER_KEY", resolved)

    configuration = ConfigurationLoader().load(LIVE_PROFILE)

    gateway = configuration.providers["provider.litellm_gateway"]
    assert gateway.api_key == resolved
    # ``Configuration.to_dict`` is intentionally safe for diagnostics.
    assert "api_key" not in configuration.to_dict()["providers"]["provider.litellm_gateway"]


def test_build_application_passes_resolved_key_to_gateway_provider_without_network(monkeypatch):
    resolved = "offline-build-master-key"
    monkeypatch.setenv("ORATRICE_LITELLM_MASTER_KEY", resolved)
    captured: dict[str, object] = {}

    def gateway_factory(config):
        captured.update(dict(config))
        return LiteLLMGatewayProvider(config, session=_NoNetworkSession())

    providers = ProviderRegistry()
    providers.register("litellm_gateway", gateway_factory)
    route = RouteDecision(model="gpt_oss", provider="provider.litellm_gateway")
    router = StaticRouter(routes={"default": route}, default=route)

    application = build_application(
        LIVE_PROFILE,
        provider_registry=providers,
        router=router,
        auto_start=False,
    )
    try:
        gateway = application.facade._provider("provider.litellm_gateway", "offline-test")
        assert isinstance(gateway, LiteLLMGatewayProvider)
        assert captured["api_key"] == resolved
        assert gateway._headers()["Authorization"] == f"Bearer {resolved}"
    finally:
        application.close()


def test_live_profile_fails_closed_without_gateway_key_and_does_not_leak_value(monkeypatch):
    monkeypatch.delenv("ORATRICE_LITELLM_MASTER_KEY", raising=False)

    with pytest.raises(ConfigurationError) as raised:
        ConfigurationLoader().load(LIVE_PROFILE)

    message = str(raised.value)
    assert "ORATRICE_LITELLM_MASTER_KEY" in message
    assert "not set" in message
    assert "offline-build-master-key" not in message

