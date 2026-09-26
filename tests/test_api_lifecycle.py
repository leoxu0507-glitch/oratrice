"""FastAPI lifespan contracts without uvicorn, sockets, or model processes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from core.observability import HealthReport
from oratrice_api import create_api


class LifecycleFacade:
    def health(self, **kwargs):
        return HealthReport(
            status="healthy",
            components={},
            request_id=kwargs.get("request_id"),
        )


class LifecycleApplication:
    def __init__(self):
        self.facade = LifecycleFacade()
        self.close_calls = 0

    def close(self):
        self.close_calls += 1


def test_create_api_is_lazy_and_factory_application_closes_once():
    factory_calls: list[dict[str, object]] = []
    created: list[LifecycleApplication] = []

    def factory(**kwargs):
        factory_calls.append(dict(kwargs))
        application = LifecycleApplication()
        created.append(application)
        return application

    api = create_api(application_factory=factory, config_path="offline.yaml")
    assert factory_calls == []
    assert api.state.application is None

    with TestClient(api, raise_server_exceptions=False) as client:
        assert factory_calls == [{"config_path": "offline.yaml", "auto_start": False}]
        assert client.get("/health").status_code == 200
        assert created[0].close_calls == 0

    assert created[0].close_calls == 1


def test_injected_application_is_external_and_never_closed():
    application = LifecycleApplication()
    api = create_api(application=application)

    with TestClient(api, raise_server_exceptions=False) as client:
        assert client.get("/health").status_code == 200

    assert application.close_calls == 0


def test_factory_lifespan_never_constructs_runtime_or_provider():
    calls = {"factory": 0, "provider": 0, "process": 0, "model": 0}

    class NoSideEffectApplication(LifecycleApplication):
        def __init__(self):
            super().__init__()
            calls["model"] += 0

    def factory(**kwargs):
        calls["factory"] += 1
        assert kwargs["auto_start"] is False
        return NoSideEffectApplication()

    api = create_api(application_factory=factory)
    with TestClient(api, raise_server_exceptions=False) as client:
        assert client.get("/health").json()["healthy"] is True

    assert calls == {"factory": 1, "provider": 0, "process": 0, "model": 0}
