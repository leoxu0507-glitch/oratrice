"""Offline M6 liveness/readiness contracts for the Core API."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from core.observability import HealthReport
from oratrice_api import create_api


class _Facade:
    def __init__(self, report: HealthReport):
        self.report = report
        self.health_calls: list[dict[str, object]] = []

    def health(self, **kwargs):
        self.health_calls.append(dict(kwargs))
        return self.report


class _Application:
    def __init__(self, report: HealthReport):
        self.facade = _Facade(report)
        self.close_calls = 0

    def close(self):
        self.close_calls += 1


def _client(report: HealthReport, **kwargs):
    application = _Application(report)
    return application, TestClient(
        create_api(application=application, **kwargs),
        raise_server_exceptions=False,
    )


def test_live_is_facade_free_and_returns_utc_liveness_envelope():
    application, client = _client(HealthReport(status="unhealthy"))
    with client:
        response = client.get("/live")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "live"
    assert payload["healthy"] is True
    assert payload["components"] == {}
    assert payload["details"]["mode"] == "liveness"
    datetime.fromisoformat(payload["checked_at"]).astimezone(timezone.utc)
    assert application.facade.health_calls == []


def test_ready_requires_all_components_and_uses_configured_health_mode():
    report = HealthReport(
        status="healthy",
        components={"providers": {"required": {"status": "healthy"}}},
    )
    application, client = _client(report)
    with client:
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["healthy"] is True
    assert len(application.facade.health_calls) == 1
    assert application.facade.health_calls[0]["include_configured"] is True


def test_ready_optional_failure_is_degraded_but_non_blocking():
    report = HealthReport(
        status="unhealthy",
        components={
            "providers": {
                "required": {"status": "healthy"},
                "optional": {"status": "unhealthy", "healthy": False},
            }
        },
        details={"required": ["required"], "optional": ["optional"]},
    )
    application, client = _client(report)
    with client:
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["healthy"] is True


def test_ready_empty_or_required_failure_is_not_ready():
    empty_application, empty_client = _client(HealthReport(status="unknown", components={}))
    with empty_client:
        empty = empty_client.get("/ready")
    assert empty.status_code == 503
    assert empty.json()["status"] == "not_ready"
    assert empty.json()["healthy"] is False

    failed_application, failed_client = _client(
        HealthReport(
            status="unhealthy",
            components={"providers": {"required": {"status": "unknown"}}},
        )
    )
    with failed_client:
        failed = failed_client.get("/ready")
    assert failed.status_code == 503
    assert failed.json()["status"] == "not_ready"
    assert failed.json()["healthy"] is False


def test_ready_checker_can_supply_report_and_classification_without_facade_health():
    report = HealthReport(
        status="unhealthy",
        components={
            "providers": {
                "core": {"status": "healthy"},
                "optional": {"status": "unhealthy"},
            }
        },
    )
    application, client = _client(
        report,
        readiness_checker=lambda: {
            "report": report,
            "required": ["core"],
            "optional": ["optional"],
        },
    )
    with client:
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert application.facade.health_calls == []
