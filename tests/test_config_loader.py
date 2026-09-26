import os
from pathlib import Path

import pytest

from core.configuration import ConfigurationError, ConfigurationLoader


def write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loader_resolves_relative_paths_and_references(tmp_path):
    path = write_config(
        tmp_path,
        """
version: 1
providers:
  local:
    id: provider.local
    type: openai_compatible
    kind: local
runtimes:
  server:
    id: runtime.server
    type: executable
    executable: bin/server
    working_dir: run
    provider: provider.local
models:
  model:
    id: model.model
    runtime: runtime.server
    provider: provider.local
    path: models/model.gguf
routes:
  default:
    id: route.default
    model: model.model
    provider: provider.local
policies: {}
""",
    )
    config = ConfigurationLoader().load(path)
    assert config.models["model.model"].path == (tmp_path / "models/model.gguf").resolve()
    assert config.runtimes["runtime.server"].executable == (tmp_path / "bin/server").resolve()
    assert config.routes["route.default"].provider == "provider.local"


def test_literal_secret_is_rejected(tmp_path):
    path = write_config(
        tmp_path,
        """
version: 1
providers:
  cloud:
    id: provider.cloud
    type: openai_compatible
    kind: cloud
    api_key: sk-do-not-commit
""",
    )
    with pytest.raises(ConfigurationError, match="literal secrets"):
        ConfigurationLoader().load(path)


def test_environment_secret_is_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("ORATRICE_TEST_KEY", "test-secret")
    path = write_config(
        tmp_path,
        """
version: 1
providers:
  cloud:
    id: provider.cloud
    type: openai_compatible
    kind: cloud
    api_key: ${ORATRICE_TEST_KEY}
""",
    )
    config = ConfigurationLoader().load(path)
    assert config.providers["provider.cloud"].api_key == "test-secret"
    assert "api_key" not in config.to_dict()["providers"]["provider.cloud"]


def test_unknown_reference_is_rejected(tmp_path):
    path = write_config(
        tmp_path,
        """
version: 1
models:
  model:
    id: model.model
    runtime: runtime.missing
""",
    )
    with pytest.raises(ConfigurationError, match="unknown runtime"):
        ConfigurationLoader().load(path)


def test_legacy_resources_are_accepted(tmp_path):
    path = write_config(
        tmp_path,
        """
resources:
  runtimes:
    server:
      id: runtime.server
      executable: bin/server
  models:
    model:
      id: model.model
      runtime: runtime.server
      path: models/model.gguf
  services:
    ui:
      id: service.ui
""",
    )
    config = ConfigurationLoader().load(path)
    assert config.version == 0
    assert config.runtimes["runtime.server"].executable == (tmp_path / "bin/server").resolve()
    assert config.legacy_resources["services"]["ui"]["id"] == "service.ui"
