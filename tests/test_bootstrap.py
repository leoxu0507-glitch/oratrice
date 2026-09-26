from __future__ import annotations

from pathlib import Path

from core.application import build_application
from providers import ChatChunk, ChatResponse, ProviderRegistry


class FakeProvider:
    instances: list["FakeProvider"] = []

    def __init__(self, **config):
        self.config = config
        self.calls: list[tuple[str, object]] = []
        type(self).instances.append(self)

    def chat(self, request):
        self.calls.append(("chat", request))
        return ChatResponse(content="ok", model=request.model)

    def stream(self, request):
        self.calls.append(("stream", request))
        return iter((ChatChunk(content="o"), ChatChunk(content="k")))

    def health(self):
        return {"status": "healthy"}

    def models(self):
        return []


def _config(path: Path) -> Path:
    path.write_text(
        """version: 1
providers:
  fake:
    id: provider.fake
    type: fake
    kind: local
models:
  demo:
    id: model.demo
routes:
  default:
    id: route.default
    model: model.demo
    provider: provider.fake
""",
        encoding="utf-8",
    )
    return path


def test_build_application_wires_facade_without_constructing_provider(tmp_path):
    FakeProvider.instances.clear()
    providers = ProviderRegistry()
    providers.register("fake", FakeProvider)
    app = build_application(_config(tmp_path / "oratrice.yaml"), provider_registry=providers, auto_start=False)

    assert FakeProvider.instances == []
    response = app.facade.chat("model.demo", "hello")
    assert response.content == "ok"
    assert response.provider == "provider.fake"
    assert [chunk.content for chunk in app.facade.stream("model.demo", "hello")] == ["o", "k"]
    assert len(FakeProvider.instances) == 1


def test_compatibility_ai_service_keeps_string_chat_and_stream(tmp_path):
    providers = ProviderRegistry()
    providers.register("fake", FakeProvider)
    app = build_application(_config(tmp_path / "oratrice.yaml"), provider_registry=providers, auto_start=False)

    assert app.ai_service.chat("model.demo", "hello") == "ok"
    assert list(app.ai_service.stream("model.demo", "hello")) == ["o", "k"]
