from __future__ import annotations

from pathlib import Path

import pytest

from core.configuration import ConfigurationLoader
from launcher.orchestrator import LauncherOrchestrator


PROFILE = Path(__file__).resolve().parents[1] / "config" / "profiles" / "live.yaml"


class FakeManager:
    def __init__(self, fail=()):
        self.fail = set(fail)
        self.started = []
        self.stop_all_calls = 0

    def start(self, runtime, **kwargs):
        self.started.append((runtime, kwargs))
        if runtime["id"] in self.fail:
            raise RuntimeError("fake start failure")
        return object()

    def stop_all(self):
        self.stop_all_calls += 1
        return {}


@pytest.fixture
def configuration(monkeypatch):
    monkeypatch.setenv("ORATRICE_LITELLM_MASTER_KEY", "loader-only-key")
    return ConfigurationLoader(PROFILE).load()


def test_order_overrides_generated_secret_and_ui(configuration):
    manager = FakeManager()
    env = {}
    browsers = []
    probes = []

    def probe(url, timeout, headers=None):
        probes.append((url, dict(headers or {})))
        return url == "http://127.0.0.1:8000/live"

    launcher = LauncherOrchestrator(
        configuration,
        runtime_manager=manager,
        env=env,
        secret_factory=lambda: "generated-sensitive-value",
        health_probe=probe,
        browser_opener=browsers.append,
    )
    result = launcher.start()
    assert result.ok
    assert [runtime["id"] for runtime, _ in manager.started] == [
        "runtime.gpt_oss",
        "runtime.gemma_router",
        "runtime.litellm_gateway",
        "runtime.core_api",
    ]
    gemma_args = manager.started[1][0]["args"]
    assert gemma_args[gemma_args.index("-ngl") + 1] == "0"
    gateway = manager.started[2][0]
    assert gateway["executable"] == Path(
        r"D:\AI\infrastructure\litellm\.venv-m7-03\Scripts\litellm.exe"
    )
    assert gateway["env"]["ORATRICE_LITELLM_MASTER_KEY"] == "generated-sensitive-value"
    assert "generated-sensitive-value" not in repr(result)
    assert result.ui_status == "OPENED"
    assert browsers == ["http://127.0.0.1:8000/ui/"]
    assert any(
        headers.get("Authorization") == "Bearer generated-sensitive-value"
        for _, headers in probes
    )
    launcher.stop()
    assert "ORATRICE_LITELLM_MASTER_KEY" not in env


def test_external_reuse_is_not_started(configuration):
    manager = FakeManager()
    launcher = LauncherOrchestrator(
        configuration,
        runtime_manager=manager,
        env={"ORATRICE_LITELLM_MASTER_KEY": "existing"},
        health_probe=lambda url, *args: url == "http://127.0.0.1:8080/health",
    )
    result = launcher.start(open_ui=False)
    assert result.outcomes[0].status == "REUSED_EXTERNAL"
    assert result.outcomes[0].owned is False
    assert [runtime["id"] for runtime, _ in manager.started] == [
        "runtime.gemma_router",
        "runtime.litellm_gateway",
        "runtime.core_api",
    ]
    launcher.stop()
    assert manager.stop_all_calls == 1


def test_required_failure_rolls_back(configuration):
    manager = FakeManager(fail={"runtime.gemma_router"})
    launcher = LauncherOrchestrator(
        configuration,
        runtime_manager=manager,
        env={"ORATRICE_LITELLM_MASTER_KEY": "existing"},
        health_probe=lambda *args: False,
    )
    result = launcher.start(open_ui=False)
    assert result.status == "FAIL"
    assert [runtime["id"] for runtime, _ in manager.started] == [
        "runtime.gpt_oss",
        "runtime.gemma_router",
    ]
    assert manager.stop_all_calls == 1
    assert result.outcomes[-1].status == "FAILED"


def test_optional_failure_skips_and_precedes_gateway(configuration):
    manager = FakeManager(fail={"runtime.qwen_vl"})
    launcher = LauncherOrchestrator(
        configuration,
        runtime_manager=manager,
        env={"ORATRICE_LITELLM_MASTER_KEY": "existing"},
        health_probe=lambda *args: False,
    )
    result = launcher.start(include_optional=["qwen_vl"], open_ui=False)
    assert result.status == "PASS"
    assert [runtime["id"] for runtime, _ in manager.started] == [
        "runtime.gpt_oss",
        "runtime.gemma_router",
        "runtime.qwen_vl",
        "runtime.litellm_gateway",
        "runtime.core_api",
    ]
    assert next(item for item in result.outcomes if item.id == "qwen_vl").status == "SKIPPED"
    launcher.stop()


def test_dry_run_has_zero_side_effects(configuration):
    manager = FakeManager()
    env = {}
    calls = []
    launcher = LauncherOrchestrator(
        configuration,
        runtime_manager=manager,
        env=env,
        secret_factory=lambda: calls.append("secret") or "secret",
        health_probe=lambda *args: calls.append("probe") or False,
        browser_opener=lambda url: calls.append("browser"),
    )
    result = launcher.start(dry_run=True, include_optional=["qwen_vl"])
    assert result.ok and result.dry_run
    assert all(item.status == "PLANNED" for item in result.outcomes)
    assert manager.started == []
    assert calls == []
    assert env == {}


def test_unavailable_ui_is_non_fatal(configuration):
    manager = FakeManager()
    browsers = []
    launcher = LauncherOrchestrator(
        configuration,
        runtime_manager=manager,
        env={"ORATRICE_LITELLM_MASTER_KEY": "existing"},
        health_probe=lambda *args: False,
        browser_opener=browsers.append,
    )
    result = launcher.start()
    assert result.ok
    assert result.ui_status == "SKIPPED_UNAVAILABLE"
    assert browsers == []
    launcher.stop()
