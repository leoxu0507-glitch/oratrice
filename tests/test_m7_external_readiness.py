"""Focused M7 contract tests for lazy external endpoint readiness."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from oratrice_api import create_api
from providers.external_readiness import ExternalEndpointReadinessProvider


PROFILE = """
version: 1
models: {}
runtimes: {}
providers: {}
routes: {}
policies: {}
defaults:
  launcher:
    targets:
      - id: required_a
        health_endpoint: http://127.0.0.1:8101/health
      - id: required_b
        health_endpoint: http://127.0.0.1:8102/health
        required_env:
          - SECRET_ENV_NAME
    optional_targets:
      - id: optional_a
        health_endpoint: http://127.0.0.1:8103/health
"""


def _write_profile(tmp_path: Path, text: str = PROFILE) -> Path:
    path = tmp_path / "live.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_provider_is_lazy_and_checks_only_default_required_targets(tmp_path: Path):
    profile = _write_profile(tmp_path)
    calls: list[tuple[str, float]] = []
    seen_authorization: list[str | None] = []

    def opener(endpoint: str, timeout: float, headers):
        calls.append((endpoint, timeout))
        seen_authorization.append(headers.get("Authorization"))
        return {"status_code": 200}

    provider = ExternalEndpointReadinessProvider(
        profile,
        opener=opener,
        environ={"SECRET_ENV_NAME": "must-not-appear"},
    )
    assert calls == []
    result = provider.check_readiness()
    assert [item[0] for item in calls] == [
        "http://127.0.0.1:8101/health",
        "http://127.0.0.1:8102/health",
    ]
    assert result["required"] == ["required_a", "required_b"]
    assert result["optional"] == []
    assert result["report"]["status"] == "healthy"
    assert seen_authorization == [None, "Bearer must-not-appear"]
    assert "must-not-appear" not in repr(result)


def test_api_ready_uses_injected_provider_without_facade_health(tmp_path: Path):
    profile = _write_profile(tmp_path)

    def opener(endpoint: str, timeout: float, headers):
        del endpoint, timeout, headers
        return {"status_code": 200}

    provider = ExternalEndpointReadinessProvider(
        profile,
        opener=opener,
        environ={"SECRET_ENV_NAME": "test-only"},
    )

    class Application:
        def close(self):
            return None

    class Facade:
        def health(self, **kwargs):
            raise AssertionError(f"unexpected facade health call: {kwargs}")

    app = Application()
    app.facade = Facade()
    with TestClient(create_api(application=app, readiness_provider=provider)) as client:
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["healthy"] is True
    assert response.json()["components"]["launcher"]["required_a"]["healthy"] is True


def test_ready_endpoint_is_never_probed(tmp_path: Path):
    profile = _write_profile(
        tmp_path,
        PROFILE.replace("http://127.0.0.1:8101/health", "http://127.0.0.1:8101/ready"),
    )
    calls: list[str] = []
    provider = ExternalEndpointReadinessProvider(
        profile,
        opener=lambda endpoint, timeout, headers: calls.append(endpoint),
        environ={"SECRET_ENV_NAME": "test-only"},
    )
    result = provider()
    assert calls == [
        "http://127.0.0.1:8102/health",
    ]
    assert result["report"]["status"] == "not_ready"
    assert result["report"]["components"]["launcher"]["required_a"]["error"] == (
        "RecursiveReadinessEndpoint"
    )
