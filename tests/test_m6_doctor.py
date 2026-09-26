from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import textwrap

from launcher.cli import run
from launcher.doctor import STATUS_FAIL, STATUS_WARN, check


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "config" / "profiles" / "live.yaml"


def test_doctor_is_offline_and_restores_environment(monkeypatch):
    original = "doctor-original-value"
    monkeypatch.setenv("ORATRICE_LITELLM_MASTER_KEY", original)

    def forbidden(*args, **kwargs):
        raise AssertionError("doctor must not access process or network")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    report = check(PROFILE, environ={})

    assert report.to_dict()["offline"] is True
    assert report.to_dict()["probe_performed"] is False
    # Dependency availability is host-specific; the structural checks must
    # remain offline even when a developer has not installed every package.
    assert all(
        item.status != STATUS_FAIL
        for item in report.checks
        if item.name in {"config.parse", "launcher.plan", "aliases"}
    )
    assert "doctor-original-value" not in json.dumps(report.to_dict())
    assert os.environ["ORATRICE_LITELLM_MASTER_KEY"] == original


def test_doctor_json_is_machine_readable_and_probe_is_non_live(monkeypatch):
    monkeypatch.delenv("ORATRICE_LITELLM_MASTER_KEY", raising=False)
    output: list[str] = []

    code = run(
        ["doctor", "--profile", str(PROFILE), "--json", "--probe"],
        environ={},
        output=output.append,
    )

    payload = json.loads(output[-1])
    assert code == payload["exit_code"]
    assert payload["mode"] == "offline"
    assert payload["offline"] is True
    assert payload["probe_requested"] is True
    assert payload["probe_performed"] is False
    assert any(item["name"] == "probe" and item["status"] == STATUS_WARN for item in payload["checks"])
    assert "doctor-original-value" not in output[-1]


def test_optional_cloud_credential_is_not_a_default_failure(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    report = check(PROFILE, environ={})
    environment = next(item for item in report.checks if item.name == "environment")
    assert environment.status != STATUS_FAIL
    # A value supplied by a caller is never copied into the report.
    assert "optional-deepseek-secret" not in json.dumps(report.to_dict())


def test_shared_gateway_alias_is_allowed_for_distinct_providers():
    report = check(
        PROFILE,
        environ={"ORATRICE_LITELLM_MASTER_KEY": "doctor-placeholder"},
    )
    aliases = next(item for item in report.checks if item.name == "aliases")
    assert aliases.status != STATUS_FAIL


def test_doctor_reports_structural_alias_failure(tmp_path):
    profile = tmp_path / "broken-alias.yaml"
    profile.write_text(
        textwrap.dedent(
            """
            version: 1
            providers:
              provider:
                id: provider.local
                name: local
                type: openai_compatible
                kind: local
            runtimes:
              runtime:
                id: runtime.local
                name: local
                type: executable
                provider: provider.local
            models:
              first:
                id: model.first
                name: first
                runtime: runtime.local
                provider: provider.local
                alias: duplicate
              second:
                id: model.second
                name: second
                runtime: runtime.local
                provider: provider.local
                alias: duplicate
            routes:
              default:
                id: route.default
                model: model.first
                provider: provider.local
            policies:
              local:
                id: policy.local
                name: local
            defaults:
              launcher:
                targets:
                  - id: local
                    runtime: runtime.local
                optional_targets: []
                ui_url: http://127.0.0.1:3000/
                ui_health_url: http://127.0.0.1:3000/
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    report = check(profile, environ={})
    aliases = next(item for item in report.checks if item.name == "aliases")
    assert aliases.status == STATUS_FAIL
    assert report.exit_code == 1


def test_doctor_reports_parse_failure_without_echoing_profile_values(tmp_path):
    profile = tmp_path / "invalid.yaml"
    profile.write_text("version: [not valid\n", encoding="utf-8")

    report = check(profile, environ={"SECRET_VALUE": "never-print-this"})
    payload = report.to_dict()
    assert payload["status"] == STATUS_FAIL
    assert any(item.name == "config.parse" and item.status == STATUS_FAIL for item in report.checks)
    assert "never-print-this" not in json.dumps(payload)
