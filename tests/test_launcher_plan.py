from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from core.configuration import ConfigurationLoader
from launcher.plan import LaunchPlan, LaunchPlanError


PROFILE = Path(__file__).resolve().parents[1] / "config" / "profiles" / "live.yaml"


@pytest.fixture
def live_config(monkeypatch):
    monkeypatch.setenv("ORATRICE_LITELLM_MASTER_KEY", "offline-launch-plan-key")
    return ConfigurationLoader(PROFILE).load()


def test_live_launch_plan_is_ordered_local_first_and_side_effect_free(
    live_config, monkeypatch
):
    def forbidden(*args, **kwargs):
        raise AssertionError("launch plan parsing must not perform side effects")

    monkeypatch.setattr("subprocess.Popen", forbidden)
    monkeypatch.setattr("webbrowser.open", forbidden)

    plan = LaunchPlan.from_configuration(live_config)

    assert [target.runtime_id for target in plan.targets] == [
        "runtime.gpt_oss",
        "runtime.gemma_router",
        "runtime.litellm_gateway",
        "runtime.core_api",
    ]
    assert plan.targets[0].timeout == 180
    assert plan.targets[0].health_endpoint == "http://127.0.0.1:8080/health"
    assert dict(plan.targets[1].argument_overrides) == {"-ngl": "0"}
    gateway = plan.targets[2]
    assert gateway.executable_override == Path(
        r"D:\AI\infrastructure\litellm\.venv-m7-03\Scripts\litellm.exe"
    )
    assert gateway.required_env == ("ORATRICE_LITELLM_MASTER_KEY",)
    assert gateway.generate_if_missing is True
    assert gateway.health_endpoint == "http://127.0.0.1:4000/health/liveliness"
    core_api = plan.targets[3]
    assert core_api.timeout == 60
    assert core_api.executable_override == Path(
        r"D:\AI\projects\Oratrice\.venv\Scripts\python.exe"
    )
    assert core_api.health_endpoint == "http://127.0.0.1:8000/health"
    assert [target.runtime_id for target in plan.optional_targets] == ["runtime.qwen_vl"]
    assert plan.optional_targets[0].optional is True
    assert plan.optional_targets[0].before == "litellm_gateway"
    assert [target.id for target in plan.selected_targets(["qwen_vl"])] == [
        "gpt_oss",
        "gemma_router",
        "qwen_vl",
        "litellm_gateway",
        "core_api",
    ]
    assert plan.ui_url == "http://127.0.0.1:8000/ui/"
    assert plan.ui_health_url == "http://127.0.0.1:8000/live"
    assert plan.open_ui_if_available is True
    assert plan.attempt_limit == 3


@pytest.mark.parametrize(
    "mutate, match",
    [
        (
            lambda raw: raw["targets"][0].update(runtime="runtime.missing"),
            "unknown runtime",
        ),
        (
            lambda raw: raw["targets"][1].update(id=raw["targets"][0]["id"]),
            "duplicate launcher target",
        ),
        (
            lambda raw: raw["targets"][0].update(timeout=0),
            "positive number",
        ),
    ],
)
def test_bad_launcher_configuration_fails_closed(live_config, mutate, match):
    defaults = dict(live_config.defaults)
    launcher = dict(defaults["launcher"])
    launcher["targets"] = [dict(item) for item in launcher["targets"]]
    launcher["optional_targets"] = [dict(item) for item in launcher["optional_targets"]]
    mutate(launcher)
    defaults["launcher"] = launcher
    broken = replace(live_config, defaults=defaults)

    with pytest.raises(LaunchPlanError, match=match):
        LaunchPlan.from_configuration(broken)
