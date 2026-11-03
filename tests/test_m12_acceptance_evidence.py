"""Offline contract tests for M12 acceptance evidence collection.

All process and listener observations below are fakes. No native process API,
socket connection, model, or service is started by this module.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess

import pytest

from scripts import m12_acceptance as acceptance


REVISION = "a" * 40
LOCAL_ENDPOINT = "http://127.0.0.1:9123/health"
LAUNCHER_PID = 31001
CREATED = 134100000000000000


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "work").mkdir()
    profile = root / "minimal.yaml"
    monkeypatch.setattr(acceptance, "PROJECT_ROOT", root)
    monkeypatch.chdir(root)
    return root, profile


def _profile_text(endpoint: str = LOCAL_ENDPOINT, *, include_secret_reference: bool = False) -> str:
    provider = ""
    if include_secret_reference:
        # Construct the env reference in pieces so the test source itself has
        # no interpolated credential value.
        secret_reference = "$" + "{M12_TEST_CREDENTIAL}"
        provider = (
            "providers:\n"
            "  offline:\n"
            "    api_key: \"" + secret_reference + "\"\n"
        )
    return f"""version: 1
{provider}runtimes:
  api:
    type: executable
defaults:
  launcher:
    targets:
      - id: api
        runtime: api
        health_endpoint: "{endpoint}"
    ui_url: http://127.0.0.1:9123/ui/
    ui_health_url: http://127.0.0.1:9123/live
"""


def _prepare(
    project,
    *,
    endpoint: str = LOCAL_ENDPOINT,
    output: Path = Path("work/run-1"),
    attempt: int = 1,
    include_secret_reference: bool = False,
):
    root, profile = project
    profile.write_text(
        _profile_text(endpoint, include_secret_reference=include_secret_reference),
        encoding="utf-8",
    )
    record = acceptance.prepare(
        Path(profile.name),
        output,
        revision=REVISION,
        attempt=attempt,
        hypothesis="offline evidence preparation has no native side effects",
        kind="surrogate",
        soak_minutes=30,
    )
    run = output if output.is_absolute() else root / output
    return run, record


class FakeNative:
    """Stand-in using the acceptance Windows adapter's state vocabulary."""
    def __init__(self):
        self.current = {}
        self.tree = []

    def memory_snapshot(self):
        return {"rss_bytes": 1234}

    def process_identity(self, pid):
        return dict(self.current.get(pid, {"pid": pid, "state": "gone"}))

    def process_tree(self, root_pid):
        return [dict(row) for row in self.tree]


def _install_fake_observers(monkeypatch, native, listener_state="free"):
    monkeypatch.setattr(acceptance, "_windows", lambda: native)
    monkeypatch.setattr(
        acceptance,
        "listeners",
        lambda endpoints: [
            {"target": endpoint["target"], "state": listener_state}
            for endpoint in endpoints
        ],
    )


def _observed_launch(project, monkeypatch, *, pid=LAUNCHER_PID):
    run, _ = _prepare(project)
    native = FakeNative()
    _install_fake_observers(monkeypatch, native)
    identity = {"pid": pid, "created": CREATED, "state": "running"}
    native.current[pid] = identity
    native.tree = [identity]
    baseline = acceptance.observe(run, "baseline")
    assert baseline["status"] == "PASS"
    cold_start = acceptance.observe(run, "cold-start", launcher_pid=pid)
    assert cold_start["status"] == "OBSERVED"
    return run, native


def test_prepare_uses_real_minimal_profile_without_network_process_or_native_calls(
    project, monkeypatch
):
    root, profile = project
    secret = "m12-local-secret-value"
    monkeypatch.setenv("M12_TEST_CREDENTIAL", secret)
    monkeypatch.delenv("ORATRICE_LITELLM_MASTER_KEY", raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("prepare must not touch native, network, or process APIs")

    monkeypatch.setattr(acceptance, "_windows", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "call", forbidden)
    monkeypatch.setattr(os, "kill", forbidden)

    run, record = _prepare(
        project,
        include_secret_reference=True,
        output=Path("work/portable-run"),
    )

    evidence_text = (run / "evidence.json").read_text(encoding="utf-8")
    assert record["endpoints"] == [{"target": "api", "url": LOCAL_ENDPOINT}]
    assert record["ui_url"] == "http://127.0.0.1:9123/ui/"
    assert secret not in evidence_text
    assert secret not in record["profile"]
    assert "ORATRICE_LITELLM_MASTER_KEY" not in os.environ
    assert run == root / "work" / "portable-run"
    assert profile == root / "minimal.yaml"


def test_prepare_accepts_relative_inputs_and_keeps_log_paths_relative(project):
    root, profile = project
    run, record = _prepare(project, output=Path("work/relative-run"))

    assert run == root / "work" / "relative-run"
    assert record["profile"] == str(profile.resolve())
    assert record["logs"]["cold-start"]["stdout"] == "cold-start.stdout.log"
    assert record["logs"]["restart"]["stderr"] == "restart.stderr.log"
    assert all(
        not Path(path).is_absolute()
        for streams in record["logs"].values()
        for path in streams.values()
    )


def test_prepare_never_overwrites_an_existing_run_or_evidence(project):
    run, _ = _prepare(project)
    evidence = run / "evidence.json"
    extra = run / "cold-start.stdout.log"
    evidence.write_text("operator evidence", encoding="utf-8")
    extra.write_text("operator log", encoding="utf-8")

    with pytest.raises(FileExistsError):
        _prepare(project)

    assert evidence.read_text(encoding="utf-8") == "operator evidence"
    assert extra.read_text(encoding="utf-8") == "operator log"


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://8.8.8.8:9123/health",
        "https://127.0.0.1:9123/health",
        "http://user:password@127.0.0.1:9123/health",
        "http://127.0.0.1:9123/health?token=hidden",
    ],
)
def test_prepare_rejects_unsafe_acceptance_urls_before_creating_output(project, endpoint):
    root, _ = project
    run = root / "work" / "unsafe-run"

    with pytest.raises(acceptance.EvidenceError):
        _prepare(project, endpoint=endpoint, output=Path("work/unsafe-run"))

    assert not run.exists()


def test_prepare_rejects_attempts_above_the_bounded_limit(project):
    root, _ = project

    with pytest.raises(acceptance.EvidenceError):
        _prepare(project, attempt=4, output=Path("work/fourth-attempt"))

    assert not (root / "work" / "fourth-attempt").exists()


@pytest.mark.parametrize(
    ("listener_state", "expected_status"),
    [("free", "PASS"), ("listening", "BLOCKED"), ("unknown", "BLOCKED")],
)
def test_baseline_requires_every_listener_to_be_free(project, monkeypatch, listener_state, expected_status):
    run, _ = _prepare(project)
    native = FakeNative()
    _install_fake_observers(monkeypatch, native, listener_state=listener_state)

    row = acceptance.observe(run, "baseline")

    assert row["listeners"] == [{"target": "api", "state": listener_state}]
    assert row["status"] == expected_status


def test_observation_records_process_identity_as_pid_and_creation_time(project, monkeypatch):
    run, _ = _observed_launch(project, monkeypatch)
    _, record = acceptance.load(run)

    assert record["roots"] == [{"pid": LAUNCHER_PID, "created": CREATED}]
    assert record["tracked"] == [{"pid": LAUNCHER_PID, "created": CREATED}]
    assert record["observations"][-1]["processes"] == [
        {"pid": LAUNCHER_PID, "created": CREATED, "state": "running"}
    ]


def test_soak_observation_rejects_reused_launcher_pid(project, monkeypatch):
    run, native = _observed_launch(project, monkeypatch)
    native.current[LAUNCHER_PID] = {
        "pid": LAUNCHER_PID,
        "created": 134100000100000000,
        "state": "running",
    }
    native.tree = [native.current[LAUNCHER_PID]]

    with pytest.raises(acceptance.EvidenceError, match="PID was reused"):
        acceptance.observe(run, "soak", launcher_pid=LAUNCHER_PID)


def test_cleanup_blocks_a_genuine_survivor_with_the_same_creation_identity(project, monkeypatch):
    run, native = _observed_launch(project, monkeypatch)
    native.current[LAUNCHER_PID] = {
        "pid": LAUNCHER_PID,
        "created": CREATED,
        "state": "running",
    }

    row = acceptance.cleanup(run, manual_intervention=False)

    assert row["status"] == "BLOCKED"
    assert row["survivors"] == [{"pid": LAUNCHER_PID, "created": CREATED}]


def test_cleanup_does_not_mistake_pid_reuse_for_the_owned_process(project, monkeypatch):
    run, native = _observed_launch(project, monkeypatch)
    native.current[LAUNCHER_PID] = {
        "pid": LAUNCHER_PID,
        "created": 134100000200000000,
        "state": "running",
    }

    row = acceptance.cleanup(run, manual_intervention=False)

    assert row["status"] == "PASS"
    assert row["survivors"] == []
    assert row["unknown"] == []


def test_access_denied_unknown_identity_blocks_cleanup(project, monkeypatch):
    run, native = _observed_launch(project, monkeypatch)
    native.current[LAUNCHER_PID] = {"pid": LAUNCHER_PID, "state": "unknown"}

    row = acceptance.cleanup(run, manual_intervention=False)

    assert row["status"] == "BLOCKED"
    assert row["unknown"] == [{"pid": LAUNCHER_PID, "created": CREATED}]


def test_incomplete_process_tree_keeps_cleanup_blocked(project, monkeypatch):
    run, native = _observed_launch(project, monkeypatch)
    native.tree = [
        {"pid": LAUNCHER_PID, "created": CREATED, "state": "running"},
        {"pid": LAUNCHER_PID + 1, "state": "unknown"},
    ]
    row = acceptance.observe(run, "soak", launcher_pid=LAUNCHER_PID)
    assert row["status"] == "BLOCKED"

    native.current[LAUNCHER_PID] = {"pid": LAUNCHER_PID, "state": "gone"}
    cleanup_row = acceptance.cleanup(run, manual_intervention=False)

    assert cleanup_row["status"] == "BLOCKED"
    assert cleanup_row["identity_gaps"] == [{"at": row["at"], "pid": LAUNCHER_PID + 1}]


def test_cleanup_cannot_pass_without_any_observed_owned_identity(project, monkeypatch):
    run, _ = _prepare(project)
    native = FakeNative()
    _install_fake_observers(monkeypatch, native)

    with pytest.raises(acceptance.EvidenceError, match="No observed owned-process identities"):
        acceptance.cleanup(run, manual_intervention=False)


def test_manual_cleanup_is_never_automatic_pass(project, monkeypatch):
    run, native = _observed_launch(project, monkeypatch)
    native.current[LAUNCHER_PID] = {"pid": LAUNCHER_PID, "state": "gone"}

    row = acceptance.cleanup(run, manual_intervention=True)

    assert row["status"] == "BLOCKED"
    assert row["manual_intervention"] is True


def test_observe_rejects_profile_drift_before_os_or_tcp_observation(project, monkeypatch):
    run, _ = _prepare(project)
    _, profile = project
    profile.write_text(_profile_text().replace("/health", "/changed"), encoding="utf-8")
    calls = []

    monkeypatch.setattr(acceptance, "_windows", lambda: calls.append("windows"))
    monkeypatch.setattr(acceptance, "listeners", lambda endpoints: calls.append("listeners"))

    with pytest.raises(acceptance.EvidenceError, match="Profile changed"):
        acceptance.observe(run, "baseline")

    assert calls == []


@pytest.mark.parametrize(
    "arguments",
    [
        ["observe", "--phase", "baseline"],
        ["cleanup"],
    ],
)
def test_main_without_live_flag_has_no_os_or_tcp_side_effects(project, monkeypatch, capsys, arguments):
    root, _ = project
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("a command without --live must stop before observation")

    monkeypatch.setattr(acceptance, "_windows", forbidden)
    monkeypatch.setattr(acceptance, "listeners", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    run = root / "work" / "does-not-exist"
    argv = [arguments[0], "--run", str(run), *arguments[1:]]

    result = acceptance.main(argv)
    output = json.loads(capsys.readouterr().out)

    assert result == 2
    assert output["error_type"] == "EvidenceError"
    assert calls == []
    assert not run.exists()


def test_passing_operator_checkpoint_never_changes_release_disposition(project, capsys):
    run, record = _prepare(project)

    result = acceptance.main(
        [
            "checkpoint",
            "--run",
            str(run),
            "--phase",
            "chat",
            "--result",
            "PASS",
            "--note",
            "operator reports a successful chat checkpoint",
        ]
    )
    output = json.loads(capsys.readouterr().out)
    _, persisted = acceptance.load(run)

    assert result == 0
    assert output["status"] == "RECORDED"
    assert output["release_disposition"] == "DEFERRED"
    assert record["release_disposition"] == persisted["release_disposition"] == "DEFERRED"
    assert persisted["checkpoints"][0]["result"] == "PASS"

def test_root_identity_race_blocks_and_does_not_adopt_replacement_tree(project, monkeypatch):
    run, _ = _prepare(project)
    native = FakeNative()
    _install_fake_observers(monkeypatch, native)
    native.current[LAUNCHER_PID] = {
        "pid": LAUNCHER_PID,
        "created": CREATED,
        "state": "running",
    }
    replacement = {
        "pid": LAUNCHER_PID,
        "created": 134100000300000000,
        "state": "running",
    }
    native.tree = [
        replacement,
        {"pid": LAUNCHER_PID + 1, "created": 134100000300000001, "state": "running"},
    ]
    assert acceptance.observe(run, "baseline")["status"] == "PASS"

    row = acceptance.observe(run, "cold-start", launcher_pid=LAUNCHER_PID)
    _, record = acceptance.load(run)

    assert row["status"] == "BLOCKED"
    assert record["tracked"] == []
    assert record["identity_gaps"] == [{"at": row["at"], "pid": LAUNCHER_PID}]
    with pytest.raises(acceptance.EvidenceError, match="No observed owned-process identities"):
        acceptance.cleanup(run, manual_intervention=False)


def test_known_gone_descendant_does_not_create_an_identity_gap(project, monkeypatch):
    run, native = _observed_launch(project, monkeypatch)
    native.tree = [
        {"pid": LAUNCHER_PID, "created": CREATED, "state": "running"},
        {"pid": LAUNCHER_PID + 1, "created": 134100000400000000, "state": "gone"},
    ]

    row = acceptance.observe(run, "soak", launcher_pid=LAUNCHER_PID)
    _, record = acceptance.load(run)

    assert row["status"] == "OBSERVED"
    assert record["identity_gaps"] == []
    assert record["tracked"] == [{"pid": LAUNCHER_PID, "created": CREATED}]

    native.current[LAUNCHER_PID] = {"pid": LAUNCHER_PID, "state": "gone"}
    cleanup_row = acceptance.cleanup(run, manual_intervention=False)
    assert cleanup_row["status"] == "PASS"

def test_old_cleanup_cannot_authorize_a_third_launcher_after_restart_two(project, monkeypatch):
    run, _ = _prepare(project)
    native = FakeNative()
    _install_fake_observers(monkeypatch, native)
    assert acceptance.observe(run, "baseline")["status"] == "PASS"

    root1 = {"pid": LAUNCHER_PID, "created": CREATED, "state": "running"}
    native.current[root1["pid"]] = root1
    native.tree = [root1]
    assert acceptance.observe(run, "cold-start", launcher_pid=root1["pid"])["status"] == "OBSERVED"

    native.current[root1["pid"]] = {"pid": root1["pid"], "state": "gone"}
    cleanup1 = acceptance.cleanup(run, manual_intervention=False)
    assert cleanup1["status"] == "PASS"
    assert cleanup1["root"] == {"pid": root1["pid"], "created": root1["created"]}

    root2 = {"pid": LAUNCHER_PID + 1, "created": 134100000500000000, "state": "running"}
    native.current[root2["pid"]] = root2
    native.tree = [root2]
    restart2 = acceptance.observe(run, "restart", launcher_pid=root2["pid"])
    assert restart2["status"] == "OBSERVED"

    root3 = {"pid": LAUNCHER_PID + 2, "created": 134100000600000000, "state": "running"}
    native.current[root3["pid"]] = root3
    native.tree = [root3]
    with pytest.raises(acceptance.EvidenceError, match="Verify prior cleanup"):
        acceptance.observe(run, "restart", launcher_pid=root3["pid"])

    _, record = acceptance.load(run)
    assert record["roots"] == [
        {"pid": root1["pid"], "created": root1["created"]},
        {"pid": root2["pid"], "created": root2["created"]},
    ]
    assert record["cleanup"][-1]["root"] == record["roots"][0]
    assert record["tracked"] == [
        {"pid": root1["pid"], "created": root1["created"]},
        {"pid": root2["pid"], "created": root2["created"]},
    ]
