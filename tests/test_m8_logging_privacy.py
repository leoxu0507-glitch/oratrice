"""Offline M8-00A contract checks for metadata-only LiteLLM logging."""

from pathlib import Path

from core.configuration import ConfigurationLoader
from launcher.plan import LaunchPlan


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFILE = PROJECT_ROOT / "config" / "profiles" / "live.yaml"
LITELLM_CONFIG = Path(r"D:\AI\infrastructure\litellm\config.yaml")


def test_litellm_config_disables_payload_logging():
    text = LITELLM_CONFIG.read_text(encoding="utf-8")
    assert "litellm_settings:" in text
    assert "set_verbose: false" in text
    assert "turn_off_message_logging: true" in text
    assert "log_raw_request_response: false" in text
    assert "redact_messages_in_exceptions: true" in text
    assert "redact_user_api_key_info: true" in text


def test_live_gateway_declares_log_level_without_launcher_model_constants(monkeypatch):
    monkeypatch.setenv("ORATRICE_LITELLM_MASTER_KEY", "offline-test-key")
    configuration = ConfigurationLoader(PROFILE).load()
    plan = LaunchPlan.from_configuration(configuration)
    gateway = next(target for target in plan.targets if target.id == "litellm_gateway")
    assert gateway.environment == {"LITELLM_LOG": "WARNING"}


def test_target_environment_is_only_passed_to_its_runtime(monkeypatch):
    monkeypatch.setenv("ORATRICE_LITELLM_MASTER_KEY", "offline-test-key")
    configuration = ConfigurationLoader(PROFILE).load()
    plan = LaunchPlan.from_configuration(configuration)
    gateway = next(target for target in plan.targets if target.id == "litellm_gateway")
    core = next(target for target in plan.targets if target.id == "core_api")
    assert gateway.environment == {"LITELLM_LOG": "WARNING"}
    assert core.environment == {}
