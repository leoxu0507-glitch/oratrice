from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from core.configuration import ConfigurationLoader
from launcher.cli import run
from launcher.plan import LaunchPlan


PROFILE = Path(__file__).resolve().parents[1] / "config" / "profiles" / "live.yaml"


@pytest.fixture
def live_config(monkeypatch):
    monkeypatch.setenv("ORATRICE_LITELLM_MASTER_KEY", "m4-offline-test-key")
    return ConfigurationLoader(PROFILE).load()


def test_live_profile_places_core_api_after_gateway(live_config):
    plan = LaunchPlan.from_configuration(live_config)

    assert [target.id for target in plan.targets] == [
        "gpt_oss",
        "gemma_router",
        "litellm_gateway",
        "core_api",
    ]
    core_api = plan.targets[-1]
    assert core_api.runtime_id == "runtime.core_api"
    assert core_api.timeout == 60
    assert core_api.executable_override == Path(
        r"D:\AI\projects\Oratrice\.venv\Scripts\python.exe"
    )
    assert core_api.health_endpoint == "http://127.0.0.1:8000/health"
    assert tuple(live_config.runtimes["runtime.core_api"].args)[:3] == (
        "-m",
        "uvicorn",
        "oratrice_api.main:app",
    )


@dataclass
class Outcome:
    id: str
    status: str


@dataclass
class Result:
    outcomes: tuple[Outcome, ...]
    status: str = "PASS"
    ui_status: str = "NOT_REQUESTED"

    @property
    def ok(self) -> bool:
        return self.status == "PASS"


class FakeOrchestrator:
    result = Result((Outcome("core_api", "STARTED"),))
    instances: list["FakeOrchestrator"] = []

    def __init__(self, configuration, env):
        self.configuration = configuration
        self.env = env
        self.calls: list[dict[str, object]] = []
        self.stopped = 0
        type(self).instances.append(self)

    def start(self, **kwargs):
        self.calls.append(kwargs)
        return type(self).result

    def stop(self):
        self.stopped += 1


@pytest.mark.parametrize("status", ["STARTED", "REUSED_EXTERNAL"])
def test_core_api_outcome_skips_duplicate_in_process_application(status):
    FakeOrchestrator.instances.clear()
    FakeOrchestrator.result = Result((Outcome("core_api", status),))
    application_calls: list[object] = []
    output: list[str] = []

    code = run(
        ["--no-browser"],
        orchestrator_factory=FakeOrchestrator,
        application_factory=lambda **kwargs: application_calls.append(kwargs),
        waiter=lambda: None,
        environ={},
        output=output.append,
    )

    assert code == 0
    assert application_calls == []
    assert "Oratrice API: READY" in output
    assert FakeOrchestrator.instances[0].stopped == 1
