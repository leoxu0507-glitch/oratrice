"""Offline contract tests for structured text/image messages."""

from __future__ import annotations

import pytest

from core.ai_service import CoreFacade
from providers import (
    ChatRequest,
    ImagePart,
    LlamaCppProvider,
    LiteLLMGatewayProvider,
    TextPart,
)
from router import RouteDecision, StaticRouter


class _Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload
        self.closed = False

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload

    def close(self):
        self.closed = True


class _Session:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Response(
            {
                "id": "offline-mm",
                "model": kwargs["json"]["model"],
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            }
        )


def _request() -> ChatRequest:
    return ChatRequest(
        "vision-model",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this image."},
                    {
                        "type": "image_url",
                        "image_url": {"url": "https://example.test/image.png", "detail": "low"},
                    },
                ],
            }
        ],
    )


def test_structured_content_serialises_to_openai_parts_without_changing_strings():
    request = _request()
    assert request.to_payload()["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe this image."},
                {
                    "type": "image_url",
                    "image_url": {"url": "https://example.test/image.png", "detail": "low"},
                },
            ],
        }
    ]
    assert request.message == "Describe this image."
    assert request.multimodal is True

    plain = ChatRequest("text-model", message="hello")
    assert plain.to_payload()["messages"] == [{"role": "user", "content": "hello"}]
    assert plain.message == "hello"


@pytest.mark.parametrize("provider_type, url", [(LlamaCppProvider, "http://local"), (LiteLLMGatewayProvider, "http://gateway")])
def test_openai_compatible_adapters_forward_structured_payload_offline(provider_type, url):
    session = _Session()
    provider = provider_type(url, session=session)
    result = provider.chat(_request())
    assert result.content == "ok"
    payload = session.calls[0][1]["json"]
    assert payload["messages"][0]["content"][1]["type"] == "image_url"
    assert provider.capabilities().supports_vision is True


def test_image_sources_are_strictly_validated_and_never_echoed():
    assert ImagePart("data:image/png;base64,AA==").to_dict()["image_url"]["url"].startswith("data:image/")
    with pytest.raises(ValueError) as raised:
        ImagePart("file:///tmp/PRIVATE_PROMPT_IMAGE.png")
    assert "PRIVATE_PROMPT_IMAGE" not in str(raised.value)

    with pytest.raises(ValueError):
        ImagePart("data:text/plain;base64,AA==")
    with pytest.raises(ValueError):
        ImagePart("data:image/png;base64,not-base64")
    assert "PRIVATE_PROMPT_IMAGE" not in repr(ImagePart("https://example.test/safe.png"))
    assert "Describe this image" not in repr(TextPart("Describe this image"))


def test_core_facade_retains_parts_and_marks_vision_without_logging_content():
    class Provider:
        def __init__(self):
            self.requests = []

        def chat(self, request):
            self.requests.append(request)
            return {"content": "ok"}

    provider = Provider()
    router = StaticRouter(default=RouteDecision("vision-model", "local", requires_vision=True))
    facade = CoreFacade(
        router=router,
        provider_instances={"local": provider},
        auto_start=False,
        request_id_factory=lambda: "mm-request",
    )
    result = facade.chat("vision-model", [TextPart("look"), ImagePart("https://example.test/a.png")])
    assert result.content == "ok"
    assert provider.requests[0].multimodal is True
    assert provider.requests[0].messages[0].content[1].type == "image_url"
