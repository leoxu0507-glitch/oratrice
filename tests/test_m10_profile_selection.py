"""Configuration selection is independent of a maintainer's machine layout."""

from core.configuration import ConfigurationLoader, default_service_profile
from launcher import cli


def test_default_profile_prefers_generated_file_and_preserves_legacy_fallback(tmp_path):
    profiles = tmp_path / "config" / "profiles"
    profiles.mkdir(parents=True)
    assert default_service_profile(tmp_path) == profiles / "live.yaml"
    local = profiles / "local.yaml"
    local.mkdir()
    assert default_service_profile(tmp_path) == profiles / "live.yaml"
    local.rmdir()
    local.write_text("version: 1\n", encoding="utf-8")
    assert default_service_profile(tmp_path) == local


def test_launcher_keeps_explicit_profile_override(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    profiles = tmp_path / "config/profiles"
    profiles.mkdir(parents=True)
    local = profiles / "local.yaml"
    local.write_text("version: 1\n", encoding="utf-8")
    assert cli._parser().parse_args([]).profile == str(local)
    assert cli._parser().parse_args(["--profile", "other.yaml"]).profile == "other.yaml"


def test_profile_label_is_not_misclassified_as_a_file_path(tmp_path):
    source = tmp_path / "config.yaml"
    source.write_text(
        "version: 1\ndefaults:\n  profile: local\n  config_path: gateway.yaml\n",
        encoding="utf-8",
    )
    configuration = ConfigurationLoader(source).load()
    assert configuration.defaults["profile"] == "local"
    assert configuration.defaults["config_path"] == tmp_path / "gateway.yaml"
