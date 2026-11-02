from __future__ import annotations

from pathlib import Path

import pytest

from core.configuration import ConfigurationLoader
from launcher.plan import LaunchPlan


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "config" / "profiles" / "live.yaml"
LITELLM_ROOT = ROOT.parent.parent / "infrastructure" / "litellm"


@pytest.fixture
def live_config(monkeypatch):
    monkeypatch.setenv("ORATRICE_LITELLM_MASTER_KEY", "m7-runtime-path-test-key")
    return ConfigurationLoader(PROFILE).load()


def test_live_overrides_resolve_to_separate_environment_paths(live_config):
    plan = LaunchPlan.from_configuration(live_config)
    gateway = next(item for item in plan.targets if item.id == "litellm_gateway")
    core_api = next(item for item in plan.targets if item.id == "core_api")

    expected_gateway = (
        LITELLM_ROOT / ".venv-m7-03" / "Scripts" / "litellm.exe"
    ).resolve()
    expected_core = (ROOT / ".venv" / "Scripts" / "python.exe").resolve()
    old_gateway = (LITELLM_ROOT / ".venv" / "Scripts" / "litellm.exe").resolve()
    old_core = (LITELLM_ROOT / ".venv" / "Scripts" / "python.exe").resolve()

    assert gateway.executable_override == expected_gateway
    assert core_api.executable_override == expected_core
    assert gateway.executable_override is not None
    assert core_api.executable_override is not None
    assert gateway.executable_override.is_absolute()
    assert core_api.executable_override.is_absolute()

    # The gateway and Core API must not share the gateway-only venv.
    assert gateway.executable_override.parents[1] == LITELLM_ROOT / ".venv-m7-03"
    assert core_api.executable_override.parents[1] == ROOT / ".venv"
    assert gateway.executable_override.parents[1] != core_api.executable_override.parents[1]

    # The legacy LiteLLM venv remains available for rollback, but no live
    # launcher override may resolve into it.
    assert gateway.executable_override != old_gateway
    assert core_api.executable_override != old_core
    plan_text = repr(plan).casefold()
    assert str(old_gateway).casefold() not in plan_text
    assert str(old_core).casefold() not in plan_text


def test_gateway_runtime_installation_is_pinned_in_the_source_distribution():
    source = (ROOT / "requirements-gateway.txt").read_text(encoding="utf-8")
    assert "litellm[proxy]==1.74.3" in source
