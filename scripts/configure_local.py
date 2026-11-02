"""Generate a local-only Oratrice profile and matching LiteLLM config."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from collections.abc import Mapping
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = Path("config/profiles/local.yaml")
DEFAULT_GATEWAY_CONFIG = Path("config/gateway.local.yaml")
DEFAULT_CORE_PYTHON = Path(".venv/Scripts/python.exe")
DEFAULT_GATEWAY_EXE = Path(".gateway-venv/Scripts/litellm.exe")


def _absolute_existing_file(value: str | Path, option: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{option} must be an absolute file path")
    if not path.is_file():
        raise ValueError(f"{option} must point to an existing file")
    return path.resolve(strict=True)


def _project_file(value: str | Path | None, default: Path, project_root: Path, option: str) -> Path:
    if value is None:
        return (project_root / default).resolve(strict=False)
    path = Path(value)
    if not path.is_absolute():
        path = project_root / path
    if not path.is_file():
        raise ValueError(f"{option} must point to an existing file")
    return path.resolve(strict=True)


def _output_path(value: str | Path, project_root: Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = project_root / path
    return path.resolve(strict=False)


def _path_relative_to_config(target: Path, config_path: Path) -> str:
    try:
        relative = os.path.relpath(target, start=config_path.parent)
    except ValueError:
        # Different Windows drives have no relative path. Absolute paths remain
        # valid and are resolved consistently by ConfigurationLoader.
        return str(target)
    return relative.replace(os.sep, "/")


def _project_path_relative_to_config(target: Path, config_path: Path, project_root: Path) -> str:
    try:
        target.relative_to(project_root)
    except ValueError:
        return str(target)
    return _path_relative_to_config(target, config_path)


def _path_relative_to_working_dir(target: Path, working_dir: Path) -> str:
    try:
        relative = os.path.relpath(target, start=working_dir)
    except ValueError:
        return str(target)
    return relative.replace(os.sep, "/")


def _load_yaml_mapping(path: Path, label: str) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must contain a YAML mapping")
    return dict(value)


def _replace_placeholders(value: Any, replacements: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, Mapping):
        return {
            key: _replace_placeholders(child, replacements)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_replace_placeholders(child, replacements) for child in value]
    return value


def _dump_yaml(value: Mapping[str, Any]) -> str:
    return yaml.safe_dump(
        dict(value),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def _positive_int(value: str) -> int:
    parsed = _non_negative_int(value)
    if parsed == 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def configure_local(
    *,
    llama_server: str | Path,
    gpt_model: str | Path,
    router_model: str | Path,
    output: str | Path = DEFAULT_PROFILE,
    gateway_output: str | Path = DEFAULT_GATEWAY_CONFIG,
    core_python: str | Path | None = None,
    gateway_exe: str | Path | None = None,
    ctx_size: int = 2048,
    gpt_gpu_layers: int = 999,
    threads: int = 16,
    prompt_cache_mib: int = 0,
    project_root: str | Path = PROJECT_ROOT,
) -> tuple[Path, Path]:
    """Write a generated local profile and gateway configuration.

    The three model/runtime inputs must be absolute existing files. Optional
    Core and gateway executable overrides are project-relative when inside the
    project and otherwise remain absolute. Default executable paths are kept
    in the profile without requiring a virtual environment to exist yet.
    """

    root = Path(project_root).resolve(strict=True)
    llama_path = _absolute_existing_file(llama_server, "--llama-server")
    gpt_path = _absolute_existing_file(gpt_model, "--gpt-model")
    router_path = _absolute_existing_file(router_model, "--router-model")
    core_python_path = _project_file(core_python, DEFAULT_CORE_PYTHON, root, "--core-python")
    gateway_exe_path = _project_file(gateway_exe, DEFAULT_GATEWAY_EXE, root, "--gateway-exe")

    if isinstance(ctx_size, bool) or not isinstance(ctx_size, int) or ctx_size <= 0:
        raise ValueError("--ctx-size must be a positive integer")
    if isinstance(gpt_gpu_layers, bool) or not isinstance(gpt_gpu_layers, int) or gpt_gpu_layers < 0:
        raise ValueError("--gpt-gpu-layers must be a non-negative integer")
    if isinstance(threads, bool) or not isinstance(threads, int) or threads <= 0:
        raise ValueError("--threads must be a positive integer")
    if isinstance(prompt_cache_mib, bool) or not isinstance(prompt_cache_mib, int) or prompt_cache_mib < 0:
        raise ValueError("--prompt-cache-mib must be a non-negative integer")

    profile_path = _output_path(output, root)
    gateway_path = _output_path(gateway_output, root)
    if profile_path == gateway_path:
        raise ValueError("--output and --gateway-output must be different paths")
    for target in (profile_path, gateway_path):
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"refusing to overwrite existing output: {target}")

    profile_template_path = root / "config" / "profiles" / "local.example.yaml"
    gateway_template_path = root / "config" / "gateway.example.yaml"
    profile_template = _load_yaml_mapping(profile_template_path, "local profile template")
    gateway_template = _load_yaml_mapping(gateway_template_path, "LiteLLM gateway template")

    project_root_for_profile = _path_relative_to_config(root, profile_path)
    gateway_config_for_profile = _path_relative_to_config(gateway_path, profile_path)
    gateway_config_for_working_dir = _path_relative_to_working_dir(gateway_path, root)
    replacements = {
        "@LLAMA_SERVER@": str(llama_path),
        "@GPT_MODEL@": str(gpt_path),
        "@ROUTER_MODEL@": str(router_path),
        "@PROJECT_ROOT@": project_root_for_profile,
        "@GATEWAY_CONFIG_PATH@": gateway_config_for_profile,
        "@GATEWAY_CONFIG_ARGUMENT@": gateway_config_for_working_dir,
        "@CORE_PYTHON@": _project_path_relative_to_config(
            core_python_path, profile_path, root
        ),
        "@GATEWAY_EXE@": _project_path_relative_to_config(
            gateway_exe_path, profile_path, root
        ),
        "@CTX_SIZE@": str(ctx_size),
        "@GPT_GPU_LAYERS@": str(gpt_gpu_layers),
        "@THREADS@": str(threads),
        "@PROMPT_CACHE_MIB@": str(prompt_cache_mib),
    }
    profile_output = _replace_placeholders(profile_template, replacements)

    profile_text = _dump_yaml(profile_output)
    gateway_text = _dump_yaml(gateway_template)

    created: list[Path] = []
    try:
        for target, content in (
            (profile_path, profile_text),
            (gateway_path, gateway_text),
        ):
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("x", encoding="utf-8", newline="\n") as stream:
                created.append(target)
                stream.write(content)
    except OSError:
        for target in created:
            target.unlink(missing_ok=True)
        raise

    return profile_path, gateway_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a local-only Oratrice profile and LiteLLM gateway config."
    )
    parser.add_argument("--llama-server", required=True, help="Absolute path to an existing llama-server executable")
    parser.add_argument("--gpt-model", required=True, help="Absolute path to the GPT-OSS GGUF file")
    parser.add_argument("--router-model", required=True, help="Absolute path to the Gemma router GGUF file")
    parser.add_argument("--output", default=str(DEFAULT_PROFILE), help="Profile output path, relative to the project root by default")
    parser.add_argument(
        "--gateway-output",
        default=str(DEFAULT_GATEWAY_CONFIG),
        help="LiteLLM config output path, relative to the project root by default",
    )
    parser.add_argument("--core-python", help="Existing Core Python executable; defaults to .venv/Scripts/python.exe")
    parser.add_argument("--gateway-exe", help="Existing LiteLLM executable; defaults to .gateway-venv/Scripts/litellm.exe")
    parser.add_argument("--ctx-size", type=_positive_int, default=2048, help="Context size for both llama-server processes (default: 2048)")
    parser.add_argument("--gpt-gpu-layers", type=_non_negative_int, default=999, help="GPT-OSS GPU layers (default: 999)")
    parser.add_argument("--threads", type=_positive_int, default=16, help="Threads for both llama-server processes (default: 16)")
    parser.add_argument(
        "--prompt-cache-mib",
        type=_non_negative_int,
        default=0,
        help="Prompt cache RAM limit for both llama-server processes in MiB (default: 0, disabled)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        profile_path, gateway_path = configure_local(
            llama_server=args.llama_server,
            gpt_model=args.gpt_model,
            router_model=args.router_model,
            output=args.output,
            gateway_output=args.gateway_output,
            core_python=args.core_python,
            gateway_exe=args.gateway_exe,
            ctx_size=args.ctx_size,
            gpt_gpu_layers=args.gpt_gpu_layers,
            threads=args.threads,
            prompt_cache_mib=args.prompt_cache_mib,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Wrote local profile: {profile_path}")
    print(f"Wrote LiteLLM config: {gateway_path}")
    print("The launcher creates a process-local gateway key when ORATRICE_LITELLM_MASTER_KEY is unset.")
    print("Starting LiteLLM directly requires ORATRICE_LITELLM_MASTER_KEY in its environment.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
