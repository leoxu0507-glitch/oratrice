"""M9 launcher failure and cleanup contracts.

These tests use an injected runtime manager. They do not start processes,
open sockets, launch a browser, or load model weights.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

import pytest

from launcher.cli import GATEWAY_KEY_ENV, run
from launcher.orchestrator import LauncherOrchestrator


PROFILE = Path(__file__).resolve().parents[1] / "config" / "profiles" / "live.yaml"


class CleanupFailure(RuntimeError):
    """Injected cleanup failure used to verify propagation and retry state."""


class FakeManager:
    def __init__(self, *, fail_start=(), interrupt_start=(), stop_error=None):
        self.fail_start = set(fail_start)
        self.interrupt_start = set(interrupt_start)
        self.stop_error = stop_error
        self.started: list[str] = []
        self.stop_all_calls = 0

    def start(self, runtime, **kwargs):
        runtime_id = runtime["id"]
        self.started.append(runtime_id)
        if runtime_id in self.interrupt_start:
            raise KeyboardInterrupt()
        if runtime_id in self.fail_start:
            raise RuntimeError("injected startup failure")
        return object()

    def stop_all(self):
        self.stop_all_calls += 1
        if self.stop_error is not None:
            error, self.stop_error = self.stop_error, None
            raise error
        return {}


@pytest.fixture
def configuration(monkeypatch):
    monkeypatch.setenv("ORATRICE_LITELLM_MASTER_KEY", "m9-loader-key")
    from core.configuration import ConfigurationLoader

    return ConfigurationLoader(PROFILE).load()


def test_keyboard_interrupt_during_start_cleans_owned_state(configuration):
    manager = FakeManager(interrupt_start={"runtime.gemma_router"})
    env: dict[str, str] = {}
    launcher = LauncherOrchestrator(
        configuration,
        runtime_manager=manager,
        env=env,
        secret_factory=lambda: "generated-m9-key",
        health_probe=lambda *args: False,
    )

    with pytest.raises(KeyboardInterrupt):
        launcher.start(open_ui=False)

    assert manager.started == ["runtime.gpt_oss", "runtime.gemma_router"]
    assert manager.stop_all_calls == 1
    assert env == {}
    assert launcher._active is False


def test_cleanup_failure_propagates_and_keeps_orchestrator_retryable(configuration):
    manager = FakeManager(
        fail_start={"runtime.gemma_router"},
        stop_error=CleanupFailure("runtime still alive"),
    )
    env: dict[str, str] = {}
    launcher = LauncherOrchestrator(
        configuration,
        runtime_manager=manager,
        env=env,
        secret_factory=lambda: "generated-m9-key",
        health_probe=lambda *args: False,
    )

    with pytest.raises(CleanupFailure, match="runtime still alive"):
        launcher.start(open_ui=False)

    assert manager.stop_all_calls == 1
    assert env == {}
    assert launcher._active is True

    launcher.stop()
    assert manager.stop_all_calls == 2
    assert launcher._active is False


def test_stop_failure_restores_environment_and_preserves_active_state(configuration):
    manager = FakeManager(stop_error=CleanupFailure("cannot reap"))
    env = {GATEWAY_KEY_ENV: "generated-m9-key"}
    launcher = LauncherOrchestrator(configuration, runtime_manager=manager, env=env)
    launcher._generated_names.add(GATEWAY_KEY_ENV)
    launcher._active = True

    with pytest.raises(CleanupFailure, match="cannot reap"):
        launcher.stop()

    assert env == {}
    assert launcher._active is True
    launcher.stop()
    assert launcher._active is False


@dataclass
class Outcome:
    id: str
    status: str


@dataclass
class Result:
    status: str = "PASS"
    outcomes: tuple[Outcome, ...] = (Outcome("core_api", "STARTED"),)
    ui_status: str = "NOT_REQUESTED"

    @property
    def ok(self):
        return self.status == "PASS"


class FakeCliOrchestrator:
    instance = None

    def __init__(self, configuration, env):
        self.env = env
        self.stopped = 0
        type(self).instance = self

    def start(self, **kwargs):
        return Result()

    def stop(self):
        self.stopped += 1
        raise CleanupFailure("CLI cleanup failed")


def test_cli_restores_environment_before_propagating_cleanup_failure(
    monkeypatch,
):
    monkeypatch.delenv(GATEWAY_KEY_ENV, raising=False)
    monkeypatch.delenv("ORATRICE_CONFIG", raising=False)
    env: dict[str, str] = {}
    output: list[str] = []

    def interrupt_waiter():
        raise KeyboardInterrupt()

    code = run(
        ["--no-browser"],
        orchestrator_factory=FakeCliOrchestrator,
        waiter=interrupt_waiter,
        environ=env,
        output=output.append,
    )

    assert code == 2
    assert env == {}
    assert GATEWAY_KEY_ENV not in os.environ
    assert "ORATRICE_CONFIG" not in os.environ
    assert FakeCliOrchestrator.instance.stopped == 1
    assert "Stopping Oratrice..." in output
    assert "Oratrice launcher cleanup failed: CleanupFailure" in output
    assert "CLI cleanup failed" not in "\n".join(output)
