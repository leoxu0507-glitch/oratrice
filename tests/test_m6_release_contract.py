"""Static/configuration checks for the M6 release contract.

The tests read the contract and the live profile only. They intentionally do
not import the application, start a process, open a socket, load model
weights, or contact a provider.
"""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "config" / "profiles" / "live.yaml"
CONTRACT = ROOT / "docs" / "architecture" / "RELEASE-CONTRACT.md"
AGREEMENTS = ROOT / "AGENTS.md"


REQUIRED = {
    "gpt_oss": {
        "runtime": "runtime.gpt_oss",
        "provider": "provider.gpt_oss",
        "model": "model.gpt_oss",
        "health": "http://127.0.0.1:8080/health",
    },
    "gemma_router": {
        "runtime": "runtime.gemma_router",
        "provider": "provider.gemma_router",
        "model": "model.gemma_router",
        "health": "http://127.0.0.1:8090/health",
    },
    "litellm_gateway": {
        "runtime": "runtime.litellm_gateway",
        "provider": "provider.litellm_gateway",
        "health": "http://127.0.0.1:4000/health/liveliness",
    },
    "core_api": {
        "runtime": "runtime.core_api",
        "provider": "provider.core_api",
        "health": "http://127.0.0.1:8000/health",
    },
}


def _profile() -> dict[str, object]:
    return yaml.safe_load(PROFILE.read_text(encoding="utf-8"))


def test_release_contract_declares_states_dispositions_and_scope() -> None:
    text = CONTRACT.read_text(encoding="utf-8")

    for state in ("PLANNED", "STARTING", "READY", "DEGRADED", "FAILED"):
        assert f"`{state}`" in text
    for disposition in ("PASS", "DEGRADED", "DEFERRED", "BLOCKED"):
        assert f"`{disposition}`" in text

    assert "four required components" in text
    assert "GPT-OSS" in text
    assert "Gemma Router" in text
    assert "LiteLLM Gateway" in text
    assert "Core API" in text
    assert "Qwen-VL" in text and "DeepSeek" in text and "OpenWebUI" in text
    assert "local-only default" in text


def test_required_and_optional_contract_rows_match_live_profile() -> None:
    profile = _profile()
    text = CONTRACT.read_text(encoding="utf-8")
    defaults = profile["defaults"]
    launcher = defaults["launcher"]
    targets = launcher["targets"]

    assert [target["id"] for target in targets] == list(REQUIRED)
    assert launcher["attempt_limit"] == 3

    providers = profile["providers"]
    models = profile["models"]
    for target in targets:
        expected = REQUIRED[target["id"]]
        assert target["runtime"] == expected["runtime"]
        assert target["health_endpoint"] == expected["health"]
        for identity in expected.values():
            assert identity in text
        assert any(
            item.get("id") == expected["provider"] for item in providers.values()
        )
        if "model" in expected:
            assert any(
                item.get("id") == expected["model"] for item in models.values()
            )

    optional = launcher["optional_targets"]
    assert [target["id"] for target in optional] == ["qwen_vl"]
    assert optional[0]["runtime"] == "runtime.qwen_vl"
    assert optional[0]["health_endpoint"] == "http://127.0.0.1:8082/health"
    assert optional[0]["before"] == "litellm_gateway"

    for identity in (
        "qwen_vl",
        "runtime.qwen_vl",
        "provider.qwen_vl",
        "model.qwen_vl",
        "http://127.0.0.1:8082/health",
        "model.deepseek_reasoner",
        "route.deepseek_reasoner",
        "provider.litellm_cloud",
    ):
        assert identity in text

    # The M6 contract retains the historical optional OpenWebUI row.  The
    # active M8 launcher UI is a profile-level setting and is asserted here
    # against the loaded profile instead of changing that historical document.
    assert launcher["ui_url"] == "http://127.0.0.1:8000/ui/"
    assert launcher["ui_health_url"] == "http://127.0.0.1:8000/live"

    assert models["deepseek_reasoner"]["provider"] == "provider.litellm_cloud"
    assert profile["routes"]["deepseek_reasoner"]["policy"] == "policy.cloud_opt_in"


def test_project_agreements_record_real_commands_and_bounded_evidence() -> None:
    text = AGREEMENTS.read_text(encoding="utf-8")

    for phrase in (
        "D:\\AI\\projects\\Oratrice",
        ".\\Start-Oratrice.exe --dry-run --no-browser",
        ".\\Start-Oratrice.exe --no-browser",
        ".\\Start-Oratrice.exe --with-qwen",
        "-m pytest -q",
        "luna_worker",
        "at most three attempts",
        "setup",
        "assertion",
        "isolation",
        "provider-neutral protection zone",
    ):
        assert phrase in text
