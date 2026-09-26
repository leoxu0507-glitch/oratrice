from __future__ import annotations

from dataclasses import dataclass

from launcher.cli import GATEWAY_KEY_ENV, run


@dataclass
class Outcome:
    id: str
    status: str


@dataclass
class Result:
    status: str = "PASS"
    outcomes: tuple[Outcome, ...] = (Outcome("gpt_oss", "PLANNED"),)
    ui_status: str = "NOT_REQUESTED"

    @property
    def ok(self):
        return self.status == "PASS"


class FakeOrchestrator:
    instances = []
    result = Result()

    def __init__(self, configuration, env):
        self.configuration = configuration
        self.env = env
        self.calls = []
        self.stopped = 0
        type(self).instances.append(self)

    def start(self, **kwargs):
        self.calls.append(kwargs)
        return type(self).result

    def stop(self):
        self.stopped += 1


class FakeApplication:
    def __init__(self):
        self.closed = 0

    def close(self):
        self.closed += 1


def test_dry_run_has_no_application_wait_or_persistent_secret(monkeypatch):
    FakeOrchestrator.instances.clear()
    FakeOrchestrator.result = Result()
    env = {}
    calls = []
    code = run(
        ["--dry-run"],
        orchestrator_factory=FakeOrchestrator,
        application_factory=lambda **kwargs: calls.append("application"),
        waiter=lambda: calls.append("wait"),
        environ=env,
        output=lambda value: calls.append(value),
    )
    assert code == 0
    assert FakeOrchestrator.instances[0].calls == [
        {"include_optional": [], "dry_run": True, "open_ui": True}
    ]
    assert "application" not in calls and "wait" not in calls
    assert GATEWAY_KEY_ENV not in env


def test_real_success_builds_core_waits_cleans_up_and_does_not_leak_secret():
    FakeOrchestrator.instances.clear()
    FakeOrchestrator.result = Result(outcomes=(Outcome("gpt_oss", "STARTED"),))
    env = {}
    app = FakeApplication()
    observed = {}
    output = []

    def make_app(**kwargs):
        observed.update(kwargs)
        return app

    code = run(
        ["--no-browser"],
        orchestrator_factory=FakeOrchestrator,
        application_factory=make_app,
        waiter=lambda: None,
        environ=env,
        output=output.append,
    )
    instance = FakeOrchestrator.instances[0]
    assert code == 0
    assert instance.calls[0]["open_ui"] is False
    assert instance.stopped == 1 and app.closed == 1
    assert observed["auto_start"] is False
    assert GATEWAY_KEY_ENV not in env
    assert not any("Bearer" in line or "ORATRICE_LITELLM_MASTER_KEY" in line for line in output)


def test_with_qwen_is_explicit():
    FakeOrchestrator.instances.clear()
    FakeOrchestrator.result = Result()
    code = run(
        ["--dry-run", "--with-qwen"],
        orchestrator_factory=FakeOrchestrator,
        environ={},
        output=lambda value: None,
    )
    assert code == 0
    assert FakeOrchestrator.instances[0].calls[0]["include_optional"] == ["qwen_vl"]


def test_failed_start_returns_one_and_does_not_build_core():
    FakeOrchestrator.instances.clear()
    FakeOrchestrator.result = Result(status="FAIL", outcomes=(Outcome("gpt_oss", "FAILED"),))
    calls = []
    code = run(
        [],
        orchestrator_factory=FakeOrchestrator,
        application_factory=lambda **kwargs: calls.append("application"),
        waiter=lambda: calls.append("wait"),
        environ={},
        output=lambda value: None,
    )
    assert code == 1
    assert calls == []
    assert FakeOrchestrator.instances[0].stopped == 1
