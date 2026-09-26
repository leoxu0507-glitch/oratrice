"""Offline contracts for the optional DeepSeek-over-LiteLLM route.

These tests deliberately do not call LiteLLM, DeepSeek, or any HTTP endpoint.
The cloud credential must remain an environment reference in LiteLLM's own
configuration; Core receives only the local gateway credential.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from core.application import build_application
from core.configuration import ConfigurationLoader


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LIVE_PROFILE = PROJECT_ROOT / "config" / "profiles" / "live.yaml"
LITELLM_CONFIG = PROJECT_ROOT.parent.parent / "infrastructure" / "litellm" / "config.yaml"


def _load_live(monkeypatch):
    monkeypatch.setenv("ORATRICE_LITELLM_MASTER_KEY", "offline-m1-09-master")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    return ConfigurationLoader().load(LIVE_PROFILE)


def test_litellm_deepseek_alias_uses_only_environment_reference():
    raw = yaml.safe_load(LITELLM_CONFIG.read_text(encoding="utf-8"))
    entries = [entry for entry in raw["model_list"] if entry.get("model_name") == "deepseek_reasoner"]
    assert len(entries) == 1
    params = entries[0]["litellm_params"]
    assert params["model"] == "deepseek/deepseek-reasoner"
    assert params["api_key"] == "os.environ/DEEPSEEK_API_KEY"
    assert raw["general_settings"]["master_key"] == "os.environ/ORATRICE_LITELLM_MASTER_KEY"
    # No credential value or second key source may be hidden in this config.
    raw_text_count = LITELLM_CONFIG.read_text(encoding="utf-8").count("DEEPSEEK_API_KEY")
    assert raw_text_count == 1


def test_cloud_route_is_gateway_only_and_not_the_default(monkeypatch):
    config = _load_live(monkeypatch)

    cloud_provider = config.providers["provider.litellm_cloud"]
    assert cloud_provider.type == "litellm_gateway"
    assert cloud_provider.kind == "cloud"
    assert cloud_provider.base_url == "http://127.0.0.1:4000/v1"
    assert cloud_provider.api_key == "offline-m1-09-master"

    cloud_model = config.models["model.deepseek_reasoner"]
    assert cloud_model.provider == "provider.litellm_cloud"
    assert cloud_model.get("gateway_alias") == "deepseek_reasoner"

    cloud_route = config.routes["route.deepseek_reasoner"]
    assert cloud_route.model == "model.deepseek_reasoner"
    assert cloud_route.provider == "provider.litellm_cloud"
    assert cloud_route.policy == "policy.cloud_opt_in"
    cloud_policy = config.policies["policy.cloud_opt_in"]
    assert cloud_policy.allow_cloud is True
    assert cloud_policy.require_local is False
    assert cloud_policy.allowed_providers == ("provider.litellm_cloud",)

    # The normal route and Gemma allow-list remain local-first.  The cloud
    # candidate metadata is declarative and requires an explicit caller opt-in.
    assert config.routes["route.default"].provider == "provider.litellm_gateway"
    assert config.routes["route.default"].policy == "policy.local_only"
    router = config.defaults["router"]
    assert router["allowed_models"] == ["gpt_oss", "qwen_vl"]
    assert router["allowed_providers"] == ["provider.litellm_gateway"]
    assert router["cloud_candidates"] == [
        {
            "model": "deepseek_reasoner",
            "provider": "provider.litellm_cloud",
            "policy": "policy.cloud_opt_in",
        }
    ]


def test_application_build_does_not_require_deepseek_key(monkeypatch):
    config = _load_live(monkeypatch)
    app = build_application(configuration=config, auto_start=False)
    try:
        # Core sees a second, policy-labelled LiteLLM transport only.  It never
        # needs the provider credential used by the downstream cloud model.
        assert app.configuration.providers["provider.litellm_cloud"].api_key == "offline-m1-09-master"
        assert "DEEPSEEK_API_KEY" not in repr(app.configuration.to_dict())
        assert app.configuration.routes["route.default"].provider == "provider.litellm_gateway"
    finally:
        app.close()
