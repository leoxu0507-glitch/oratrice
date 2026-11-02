from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess

import yaml

from launcher.doctor import STATUS_FAIL, STATUS_WARN, check, run_doctor


def _profile(
    root: Path,
    *,
    model_path: str,
    optional_model_path: str | None = None,
    executable: str | None = None,
    executable_override: str | None = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    local_runtime: dict[str, object] = {
        "id": "runtime.local",
        "name": "Local runtime",
        "type": "executable",
        "executable": executable or str(root / "missing-runtime.exe"),
        "working_dir": str(root),
        "provider": "provider.local",
        "args": ["--model", model_path],
    }
    optional_runtime: dict[str, object] = {
        "id": "runtime.optional",
        "name": "Optional runtime",
        "type": "executable",
        "executable": str(root / "missing-optional-runtime.exe"),
        "working_dir": str(root / "missing-optional-directory"),
        "provider": "provider.optional",
        "args": ["--model", optional_model_path or str(root / "missing-optional.gguf")],
    }
    target: dict[str, object] = {"id": "local", "runtime": "runtime.local"}
    if executable_override is not None:
        target["executable_override"] = executable_override
    value = {
        "version": 1,
        "providers": {
            "local": {
                "id": "provider.local",
                "name": "Local",
                "type": "openai_compatible",
                "kind": "local",
            },
            "optional": {
                "id": "provider.optional",
                "name": "Optional",
                "type": "openai_compatible",
                "kind": "local",
            },
        },
        "runtimes": {"local": local_runtime, "optional": optional_runtime},
        "models": {
            "local": {
                "id": "model.local",
                "name": "Local model",
                "runtime": "runtime.local",
                "provider": "provider.local",
                "path": model_path,
            },
            "optional": {
                "id": "model.optional",
                "name": "Optional model",
                "runtime": "runtime.optional",
                "provider": "provider.optional",
                "path": optional_model_path or str(root / "missing-optional.gguf"),
            },
        },
        "routes": {
            "default": {
                "id": "route.default",
                "model": "model.local",
                "provider": "provider.local",
                "policy": "policy.local",
            }
        },
        "policies": {"local": {"id": "policy.local", "name": "Local"}},
        "defaults": {
            "launcher": {
                "targets": [target],
                "optional_targets": [{"id": "optional", "runtime": "runtime.optional"}],
                "ui_url": "http://127.0.0.1:8000/ui/",
                "ui_health_url": "http://127.0.0.1:8000/live",
            }
        },
    }
    path = root / "doctor-profile.yaml"
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    return path


def _path_check(report):
    return next(item for item in report.checks if item.name == "paths")


def test_strict_paths_fails_required_assets_but_keeps_inactive_assets_as_warnings(tmp_path):
    executable = tmp_path / "runtime.exe"
    executable.write_bytes(b"runtime placeholder")
    profile = _profile(
        tmp_path,
        model_path=str(tmp_path / "missing-required.gguf"),
        executable=str(executable),
    )

    compatible = check(profile, environ={})
    strict = check(profile, environ={}, strict_paths=True)

    assert _path_check(compatible).status == STATUS_WARN
    assert _path_check(strict).status == STATUS_FAIL
    message = _path_check(strict).message
    assert "models.model.local.path" in message
    assert "models.model.optional.path" in message
    assert "download or restore the model/mmproj asset" in message
    assert str(tmp_path) not in message

    (tmp_path / "required.gguf").write_bytes(b"model placeholder")
    ready_profile = _profile(
        tmp_path,
        model_path=str(tmp_path / "required.gguf"),
        executable=str(executable),
    )
    optional_only = _path_check(check(ready_profile, environ={}, strict_paths=True))
    assert optional_only.status == STATUS_WARN
    assert "models.model.optional.path" in optional_only.message


def test_executable_override_is_the_required_target_and_stale_runtime_path_is_ignored(tmp_path):
    model = tmp_path / "local.gguf"
    model.write_bytes(b"model placeholder")
    override = tmp_path / "override.exe"
    profile = _profile(
        tmp_path,
        model_path=str(model),
        executable=str(tmp_path / "stale-runtime.exe"),
        executable_override=str(override),
    )

    missing_override = _path_check(check(profile, environ={}, strict_paths=True))
    assert missing_override.status == STATUS_FAIL
    assert "launcher.local.executable_override" in missing_override.message
    assert "runtimes.runtime.local.executable" not in missing_override.message
    assert "install the selected runtime" in missing_override.message

    override.write_bytes(b"runtime placeholder")
    existing_override = _path_check(check(profile, environ={}, strict_paths=True))
    assert existing_override.status == STATUS_WARN  # only the inactive optional runtime is absent
    assert "runtimes.runtime.local.executable" not in existing_override.message


def test_selected_mmproj_and_service_config_files_are_required_with_field_labels(tmp_path):
    model = tmp_path / "local.gguf"
    model.write_bytes(b"model placeholder")
    executable = tmp_path / "runtime.exe"
    executable.write_bytes(b"runtime placeholder")
    mmproj = tmp_path / "missing-mmproj.gguf"
    config = tmp_path / "missing-service.yaml"
    profile = _profile(tmp_path, model_path=str(model), executable=str(executable))
    value = yaml.safe_load(profile.read_text(encoding="utf-8"))
    value["runtimes"]["local"]["args"].extend(["--mmproj", str(mmproj), "--config", str(config)])
    value["models"]["local"]["mmproj_path"] = str(mmproj)
    value["defaults"]["services"] = {
        "local": {
            "id": "service.local",
            "runtime": "runtime.local",
            "config_path": str(config),
        }
    }
    profile.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")

    paths = _path_check(check(profile, environ={}, strict_paths=True))

    assert paths.status == STATUS_FAIL
    assert "models.model.local.metadata.mmproj_path" in paths.message
    assert "defaults.services.local.config_path" in paths.message
    assert "download or restore the model/mmproj asset" in paths.message
    assert "create the required config file" in paths.message
    assert str(mmproj) not in paths.message
    assert str(config) not in paths.message


def test_nonsecret_environment_path_resolves_redacted_and_process_environment_is_restored(tmp_path, monkeypatch):
    model = tmp_path / "do-not-print-env-model.gguf"
    model.write_bytes(b"model placeholder")
    executable = tmp_path / "runtime.exe"
    executable.write_bytes(b"runtime placeholder")
    monkeypatch.setenv("ORATRICE_MODEL_FILE", "process-original-value")
    profile = _profile(
        tmp_path,
        model_path="${ORATRICE_MODEL_FILE}",
        executable=str(executable),
    )

    report = check(
        profile,
        environ={"ORATRICE_MODEL_FILE": str(model)},
        strict_paths=True,
    )
    serialized = json.dumps(report.to_dict())

    assert _path_check(report).status == STATUS_WARN  # inactive optional assets remain warnings
    assert "missing required fields" not in _path_check(report).message
    assert str(model) not in serialized
    assert model.name not in serialized
    assert os.environ["ORATRICE_MODEL_FILE"] == "process-original-value"


def test_secret_named_path_reference_is_never_expanded_or_reported(tmp_path, monkeypatch):
    secret_path = tmp_path / "secret-expanded-value.gguf"
    secret_path.write_bytes(b"must not be used")
    monkeypatch.delenv("ORATRICE_MODEL_SECRET_PATH", raising=False)
    profile = _profile(tmp_path, model_path="${ORATRICE_MODEL_SECRET_PATH}")

    report = check(
        profile,
        environ={"ORATRICE_MODEL_SECRET_PATH": str(secret_path)},
        strict_paths=True,
    )

    assert _path_check(report).status == STATUS_FAIL
    assert str(secret_path) not in json.dumps(report.to_dict())
    assert "secret-expanded-value.gguf" not in json.dumps(report.to_dict())
    assert "ORATRICE_MODEL_SECRET_PATH" not in os.environ


def test_strict_paths_remains_offline_and_default_api_stays_non_strict(tmp_path, monkeypatch):
    profile = _profile(tmp_path, model_path=str(tmp_path / "missing.gguf"))

    def forbidden(*args, **kwargs):
        raise AssertionError("offline doctor must not start a process or use a network socket")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    default_report = check(profile, environ={})
    output: list[str] = []
    default_code = run_doctor(profile, environ={}, output=output.append)
    strict_code = run_doctor(profile, environ={}, strict_paths=True, output=output.append)

    assert _path_check(default_report).status == STATUS_WARN
    assert default_code == 0
    assert strict_code == 1
