"""Offline lifecycle tests for the executable runtime controller.

The real llama.cpp executable is intentionally never started by the test
suite.  Fakes are injected for both process creation and HTTP readiness.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from core.runtime_launcher import RuntimeLauncher
from core.runtime_manager import (
    RuntimeManager,
    RuntimePortConflictError,
    RuntimeState,
    RuntimeTimeoutError,
)


@dataclass
class FakeProcess:
    pid: int = 100
    returncode: int | None = None
    terminate_calls: int = 0
    kill_calls: int = 0

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminate_calls += 1
        self.returncode = 0

    def kill(self):
        self.kill_calls += 1
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


def runtime(**overrides):
    config = {
        "id": "runtime.fake",
        "executable": "fake-runtime",
        "args": ["--port", "18080"],
    }
    config.update(overrides)
    return config


def test_start_waits_for_readiness_and_reuses_live_process():
    processes = []
    probes = []

    def runner(command, cwd=None):
        process = FakeProcess(pid=len(processes) + 100)
        processes.append((command, cwd, process))
        return process

    def probe(url, timeout=None):
        probes.append((url, timeout))
        return len(probes) >= 2

    manager = RuntimeManager(
        process_runner=runner,
        http_probe=probe,
        probe_interval=0,
        sleeper=lambda _: None,
    )

    process = manager.start(runtime())
    assert process is processes[0][2]
    assert manager.status("runtime.fake").state is RuntimeState.READY
    assert probes == [
        ("http://127.0.0.1:18080/health", None),
        ("http://127.0.0.1:18080/health", None),
    ]

    assert manager.start(runtime()) is process
    assert len(processes) == 1


def test_timeout_terminates_and_cleans_up_process():
    process = FakeProcess()
    manager = RuntimeManager(
        process_runner=lambda command, cwd=None: process,
        http_probe=lambda url, timeout=None: False,
        probe_interval=0,
        sleeper=lambda _: None,
    )

    with pytest.raises(RuntimeTimeoutError) as raised:
        manager.start(runtime(health_url="http://fake/health"), timeout=0)

    assert raised.value.status.state is RuntimeState.TIMEOUT
    assert process.terminate_calls == 1
    assert manager.processes == {}


def test_port_conflict_is_reported_with_port():
    def runner(command, cwd=None):
        raise OSError(98, "Address already in use")

    manager = RuntimeManager(process_runner=runner)
    with pytest.raises(RuntimePortConflictError) as raised:
        manager.start(runtime())

    assert raised.value.port == 18080
    assert raised.value.status.state is RuntimeState.PORT_CONFLICT
    assert "18080" in str(raised.value)


def test_launcher_keeps_legacy_status_and_stop_return_values():
    process = FakeProcess()
    launcher = RuntimeLauncher(process_runner=lambda command, cwd=None: process)
    assert launcher.start(runtime()) is process
    assert launcher.status("runtime.fake") == "running"
    assert launcher.stop("runtime.fake") is None
    assert launcher.status("runtime.fake") == "stopped"
    assert launcher.status_info("runtime.fake").state is RuntimeState.STOPPED


def test_reap_records_early_process_exit():
    process = FakeProcess(returncode=None)
    manager = RuntimeManager(process_runner=lambda command, cwd=None: process)
    manager.start(runtime(), wait_for_ready=False)
    process.returncode = 7
    status = manager.status("runtime.fake")
    assert status.state is RuntimeState.FAILED
    assert status.returncode == 7
    assert manager.processes == {}
