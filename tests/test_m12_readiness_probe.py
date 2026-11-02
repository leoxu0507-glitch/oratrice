"""Readiness must not trigger the facade's active-provider inference probes."""
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from core.ai_service import CoreFacade
from oratrice_api import create_api
from providers import ChatResponse
from providers.external_readiness import ExternalEndpointReadinessProvider
from router import RouteDecision, StaticRouter


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("profile", ["local.example.yaml", "live.yaml"])
def test_ready_after_chat_does_not_call_full_facade_health(profile):
    class Provider:
        health_calls = 0

        def chat(self, request):
            return ChatResponse(content="reply", model=request.model)

        def health(self):
            # A real Gateway's full health endpoint may perform inference.
            self.health_calls += 1
            return {"healthy": True, "status": "healthy"}

    provider = Provider()
    facade = CoreFacade(
        provider_instances={"provider.test": provider},
        router=StaticRouter(default=RouteDecision("model.test", "provider.test")),
        auto_start=False,
    )
    calls = []

    def opener(endpoint, timeout, headers):
        parsed = urlsplit(endpoint)
        calls.append(endpoint)
        if parsed.port == 8000:
            return {"status_code": client.get(parsed.path).status_code}
        return {"status_code": 200}

    readiness = ExternalEndpointReadinessProvider(
        ROOT / "config" / "profiles" / profile,
        opener=opener,
        environ={"ORATRICE_LITELLM_MASTER_KEY": "offline-placeholder"},
    )
    with TestClient(create_api(
        application=SimpleNamespace(facade=facade), readiness_provider=readiness,
    )) as client:
        assert client.post("/chat", json={"message": "hello"}).status_code == 200
        response = client.get("/ready")
        assert response.status_code == 200
        assert response.json()["healthy"] is True
    assert provider.health_calls == 0
    assert "http://127.0.0.1:8000/live" in calls
