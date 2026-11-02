"""Offline regression checks for truthful, bounded runtime shutdown."""

import subprocess

import pytest

from core.runtime_manager import RuntimeManager, RuntimeState, RuntimeStopError, RuntimeTimeoutError


class Process:
    def __init__(self, name, events, stubborn=False):
        self.pid = 321
        self.returncode = None
        self.name, self.events, self.stubborn = name, events, stubborn

    def poll(self):
        return self.returncode

    def terminate(self):
        self.events.append(self.name)
        if not self.stubborn:
            self.returncode = 0

    def kill(self):
        if not self.stubborn:
            self.returncode = -9

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired(self.name, timeout)
        return self.returncode


def test_unreaped_process_retains_ownership_and_can_be_stopped_later():
    process = Process("a", [], stubborn=True)
    manager = RuntimeManager(process_runner=lambda *a, **k: process, stop_timeout=0)
    manager.start({"id": "a", "executable": "fake"}, wait_for_ready=False)
    with pytest.raises(RuntimeStopError):
        manager.stop("a")
    assert manager.processes["a"] is process
    assert manager.status("a").state is RuntimeState.STOPPING
    assert manager.status("a").stopped_at is None
    with pytest.raises(RuntimeStopError):
        manager.start({"id": "a", "executable": "fake"}, wait_for_ready=False)
    process.stubborn = False
    assert manager.stop("a").state is RuntimeState.STOPPED
    assert not manager.processes


def test_shutdown_is_reverse_order_and_attempts_every_runtime_after_failure():
    events = []
    processes = [Process("a", events), Process("b", events, stubborn=True), Process("c", events)]
    source = iter(processes)
    manager = RuntimeManager(process_runner=lambda *a, **k: next(source), stop_timeout=0)
    for name in ("a", "b", "c"):
        manager.start({"id": name, "executable": "fake"}, wait_for_ready=False)
    with pytest.raises(RuntimeStopError):
        manager.stop_all()
    assert events == ["c", "b", "a"]
    assert set(manager.processes) == {"b"}


def test_failed_readiness_retains_process_that_resists_cleanup():
    process = Process("a", [], stubborn=True)
    manager = RuntimeManager(
        process_runner=lambda *a, **k: process,
        http_probe=lambda *a, **k: False,
        stop_timeout=0,
    )
    with pytest.raises(RuntimeTimeoutError):
        manager.start({"id": "a", "executable": "fake", "health_url": "http://fake/health"}, timeout=0)
    assert manager.processes["a"] is process


def test_interrupt_during_readiness_stops_owned_process_and_propagates():
    process = Process("a", [])

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    manager = RuntimeManager(process_runner=lambda *a, **k: process, http_probe=interrupted)
    with pytest.raises(KeyboardInterrupt):
        manager.start({"id": "a", "executable": "fake", "health_url": "http://fake/health"})
    assert process.returncode == 0
    assert not manager.processes
