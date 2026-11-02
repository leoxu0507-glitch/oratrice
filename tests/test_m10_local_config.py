"""Offline checks for generated local-only deployment configuration."""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from core.configuration import ConfigurationLoader, default_service_profile
from launcher.plan import LaunchPlan
from scripts.configure_local import configure_local, main


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _copy_templates(project_root: Path) -> None:
    profiles = project_root / "config" / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    (project_root / "config").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        PROJECT_ROOT / "config" / "profiles" / "local.example.yaml",
        profiles / "local.example.yaml",
    )
    shutil.copyfile(
        PROJECT_ROOT / "config" / "gateway.example.yaml",
        project_root / "config" / "gateway.example.yaml",
    )


def _external_files(directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = {
        "llama_server": directory / "llama server.exe",
        "gpt_model": directory / "GPT OSS model.gguf",
        "router_model": directory / "Gemma router model.gguf",
    }
    for path in paths.values():
        path.touch()
    return paths


def test_gateway_template_is_local_only_and_metadata_logging_only():
    gateway_path = PROJECT_ROOT / "config" / "gateway.example.yaml"
    gateway = yaml.safe_load(gateway_path.read_text(encoding="utf-8"))
    assert set(gateway) == {"model_list", "general_settings", "litellm_settings"}
    assert [item["model_name"] for item in gateway["model_list"]] == ["gpt_oss"]
    model = gateway["model_list"][0]["litellm_params"]
    assert model == {
        "model": "openai/gpt-oss",
        "api_base": "http://127.0.0.1:8080/v1",
        "api_key": "os.environ/ORATRICE_LITELLM_MASTER_KEY",
    }
    assert gateway["general_settings"] == {
        "master_key": "os.environ/ORATRICE_LITELLM_MASTER_KEY"
    }
    assert gateway["litellm_settings"] == {
        "set_verbose": False,
        "turn_off_message_logging": True,
        "log_raw_request_response": False,
        "redact_messages_in_exceptions": True,
        "redact_user_api_key_info": True,
    }
    assert "litellm[proxy]==1.74.3" in (
        PROJECT_ROOT / "requirements-gateway.txt"
    ).read_text(encoding="utf-8")


def test_generated_defaults_load_and_form_a_local_only_launch_plan(tmp_path, monkeypatch):
    project_root = tmp_path / "Oratrice Project"
    _copy_templates(project_root)
    files = _external_files(tmp_path / "Models and Runtime")
    monkeypatch.setenv("ORATRICE_LITELLM_MASTER_KEY", "offline-test-master-key")

    profile_path, gateway_path = configure_local(
        **files,
        project_root=project_root,
    )

    assert profile_path == project_root / "config" / "profiles" / "local.yaml"
    assert gateway_path == project_root / "config" / "gateway.local.yaml"
    assert default_service_profile(project_root) == profile_path

    raw_profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    assert set(raw_profile["models"]) == {"gemma_router", "gpt_oss"}
    assert set(raw_profile["providers"]) == {
        "gemma_router",
        "gpt_oss",
        "litellm_gateway",
        "core_api",
    }
    assert "offline-test-master-key" not in profile_path.read_text(encoding="utf-8")
    assert raw_profile["providers"]["litellm_gateway"]["api_key"] == (
        "${ORATRICE_LITELLM_MASTER_KEY}"
    )

    gpt_args = raw_profile["runtimes"]["gpt_oss"]["args"]
    router_args = raw_profile["runtimes"]["gemma_router"]["args"]
    assert gpt_args[gpt_args.index("--model") + 1] == str(files["gpt_model"].resolve())
    assert router_args[router_args.index("--model") + 1] == str(files["router_model"].resolve())
    assert gpt_args[gpt_args.index("--alias") + 1] == "gpt-oss"
    assert router_args[router_args.index("--alias") + 1] == "gemma-router"
    assert gpt_args[gpt_args.index("--gpu-layers") + 1] == "999"
    assert router_args[router_args.index("--gpu-layers") + 1] == "0"
    for args in (gpt_args, router_args):
        assert args[args.index("--ctx-size") + 1] == "2048"
        assert args[args.index("--parallel") + 1] == "1"
        assert args[args.index("-t") + 1] == "16"

    raw_gateway = yaml.safe_load(gateway_path.read_text(encoding="utf-8"))
    assert raw_gateway["general_settings"]["master_key"] == (
        "os.environ/ORATRICE_LITELLM_MASTER_KEY"
    )
    assert "offline-test-master-key" not in gateway_path.read_text(encoding="utf-8")

    configuration = ConfigurationLoader(profile_path).load()
    assert set(configuration.models) == {"model.gpt_oss", "model.gemma_router"}
    assert configuration.runtimes["runtime.gpt_oss"].executable == files["llama_server"].resolve()
    assert configuration.runtimes["runtime.gpt_oss"].working_dir == project_root.resolve()
    assert configuration.defaults["gateway"]["config_path"] == gateway_path.resolve()

    plan = LaunchPlan.from_configuration(configuration)
    assert [target.id for target in plan.targets] == [
        "gpt_oss",
        "gemma_router",
        "litellm_gateway",
        "core_api",
    ]
    gateway_target = next(target for target in plan.targets if target.id == "litellm_gateway")
    core_target = next(target for target in plan.targets if target.id == "core_api")
    assert gateway_target.required_env == ("ORATRICE_LITELLM_MASTER_KEY",)
    assert gateway_target.generate_if_missing is True
    assert gateway_target.environment == {
        "LITELLM_LOG": "WARNING",
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
    }
    assert gateway_target.executable_override == project_root / ".gateway-venv" / "Scripts" / "litellm.exe"
    assert core_target.executable_override == project_root / ".venv" / "Scripts" / "python.exe"


def test_cli_quotes_paths_and_refuses_existing_outputs(tmp_path, monkeypatch):
    project_root = tmp_path / "Project with spaces"
    _copy_templates(project_root)
    files = _external_files(tmp_path / "external paths with spaces")
    monkeypatch.setenv("ORATRICE_LITELLM_MASTER_KEY", "offline-test-master-key")
    monkeypatch.chdir(project_root)
    profile_path = project_root / "generated configs" / "local profile.yaml"
    gateway_path = project_root / "generated configs" / "gateway file.yaml"

    status = main(
        [
            "--llama-server",
            str(files["llama_server"]),
            "--gpt-model",
            str(files["gpt_model"]),
            "--router-model",
            str(files["router_model"]),
            "--output",
            str(profile_path),
            "--gateway-output",
            str(gateway_path),
            "--ctx-size",
            "4096",
            "--gpt-gpu-layers",
            "42",
            "--threads",
            "8",
        ]
    )
    assert status == 0
    raw = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    args = raw["runtimes"]["gpt_oss"]["args"]
    assert args[args.index("--ctx-size") + 1] == "4096"
    assert args[args.index("--gpu-layers") + 1] == "42"
    assert args[args.index("-t") + 1] == "8"
    assert ConfigurationLoader(profile_path).load().runtimes["runtime.gpt_oss"].working_dir == PROJECT_ROOT.resolve()

    profile_bytes = profile_path.read_bytes()
    gateway_bytes = gateway_path.read_bytes()
    try:
        configure_local(
            **files,
            output=profile_path,
            gateway_output=gateway_path,
            project_root=project_root,
        )
    except FileExistsError:
        pass
    else:
        raise AssertionError("existing outputs must not be overwritten")
    assert profile_path.read_bytes() == profile_bytes
    assert gateway_path.read_bytes() == gateway_bytes


def test_external_python_and_gateway_overrides_remain_absolute(tmp_path):
    project_root = tmp_path / "Oratrice Project"
    _copy_templates(project_root)
    files = _external_files(tmp_path / "external models")
    external_tools = tmp_path / "external tools"
    external_tools.mkdir()
    core_python = external_tools / "Core Python.exe"
    gateway_exe = external_tools / "LiteLLM.exe"
    core_python.touch()
    gateway_exe.touch()

    profile_path, _ = configure_local(
        **files,
        core_python=core_python,
        gateway_exe=gateway_exe,
        project_root=project_root,
    )
    raw = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    targets = raw["defaults"]["launcher"]["targets"]
    assert Path(targets[2]["executable_override"]) == gateway_exe.resolve()
    assert Path(targets[3]["executable_override"]) == core_python.resolve()
