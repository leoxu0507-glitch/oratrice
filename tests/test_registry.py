from pathlib import Path

import pytest
import yaml

from entities.app import App
from entities.model import Model
from entities.provider import Provider
from entities.resource import Resource
from entities.runtime import Runtime
from entities.service import Service
from core.registry import ResourceRegistry


def _write_config(tmp_path: Path, resources: dict) -> Path:
    path = tmp_path / "resources.yaml"
    path.write_text(yaml.safe_dump({"resources": resources}), encoding="utf-8")
    return path


def test_load_constructs_typed_resources_and_keeps_metadata(tmp_path):
    config = _write_config(
        tmp_path,
        {
            "runtimes": {
                "llama": {
                    "id": "runtime.llama",
                    "name": "llama.cpp",
                    "type": "executable",
                    "executable": "llama-server",
                    "working_dir": "runtime",
                    "args": ["--host", "127.0.0.1"],
                    "future_flag": True,
                }
            },
            "models": {
                "model": {
                    "id": "model.one",
                    "name": "One",
                    "runtime": "runtime.llama",
                    "path": "models/one.gguf",
                    "ctx_size": 4096,
                    "quantization": "Q4",
                }
            },
            "providers": {
                "local": {
                    "id": "provider.local",
                    "name": "Local",
                    "type": "openai_compatible",
                    "base_url": "http://127.0.0.1:8080",
                    "api_key": "secret",
                }
            },
            "services": {"service": {"id": "service.one", "name": "Svc"}},
            "apps": {"app": {"id": "app.one", "name": "App"}},
            "system": {"python": {"id": "system.python", "name": "Python"}},
        },
    )

    registry = ResourceRegistry().load(config)

    runtime = registry.get("runtime.llama")
    model = registry.get("model.one")
    provider = registry.get("provider.local")
    assert isinstance(runtime, Runtime)
    assert isinstance(model, Model)
    assert isinstance(provider, Provider)
    assert isinstance(registry.get("service.one"), Service)
    assert isinstance(registry.get("app.one"), App)
    assert isinstance(registry.get("system.python"), Resource)
    assert runtime.executable == "llama-server"
    assert runtime.args == ["--host", "127.0.0.1"]
    assert runtime.get("future_flag") is True
    assert model.runtime == "runtime.llama"
    assert model.get("runtime") == "runtime.llama"
    assert model.ctx_size == 4096
    assert model.get("quantization") == "Q4"
    assert provider.base_url == "http://127.0.0.1:8080"
    assert [item.id for item in registry.list_models()] == ["model.one"]


def test_duplicate_ids_are_rejected_across_categories(tmp_path):
    config = _write_config(
        tmp_path,
        {
            "runtimes": {"a": {"id": "same", "name": "A"}},
            "models": {"b": {"id": "same", "name": "B"}},
        },
    )

    with pytest.raises(ValueError, match="Duplicate resource id"):
        ResourceRegistry().load(config)


def test_lookup_order_and_unknown_values_are_stable(tmp_path):
    config = _write_config(
        tmp_path,
        {
            "models": {
                "first": {"id": "model.first", "name": "First"},
                "second": {"id": "model.second", "name": "Second"},
            }
        },
    )
    registry = ResourceRegistry().load(config)

    assert [m.id for m in registry.list_models()] == ["model.first", "model.second"]
    assert registry.get("missing") is None
    assert not registry.exists("missing")
    assert registry.list_category("does-not-exist") == []

