from __future__ import annotations

import json

import pytest

from router import (
    GemmaRouterProvider,
    RouteParseError,
    RouterRequest,
    RouterTransportError,
)


class FakeGemma:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def chat(self, model, message, temperature=0.7):
        self.calls.append((model, message, temperature))
        return self.response


class FakeDecisionPolicy:
    def __init__(self):
        self.requests = []
        self.decisions = []

    def prompt_candidates(self, request):
        self.requests.append(request)
        return [{"model": "model.local", "provider": "provider.local"}]

    def validate(self, request, decision):
        self.decisions.append((request, decision))


def response_json(**overrides):
    payload = {
        "model": "model.local",
        "provider": "provider.local",
        "task_type": "general",
        "complexity": "medium",
        "capabilities": ["chat"],
        "requires_vision": False,
        "requires_network": False,
        "requires_tools": False,
        "reason": "local-first",
        "confidence": 0.95,
    }
    payload.update(overrides)
    return json.dumps(payload)


def legacy_envelope(prompt):
    """Extract the JSON request from the combined legacy chat prompt."""

    marker = "ROUTING REQUEST (JSON):\n"
    body = prompt.split(marker, 1)[1]
    return json.loads(body.split("\n\nOUTPUT REQUIREMENT:", 1)[0])


def test_gemma_adapter_preserves_system_prompt_and_structured_request():
    fake = FakeGemma(response_json())
    adapter = GemmaRouterProvider(
        fake,
        model_name="router.gemma",
        allowed_models=["model.local"],
        allowed_providers=["provider.local"],
    )
    decision = adapter.route(RouterRequest("hello"))
    assert decision.model == "model.local"
    assert fake.calls[0][0] == "router.gemma"
    prompt = fake.calls[0][1]
    assert "SYSTEM INSTRUCTIONS:" in prompt
    assert "You are a routing classifier." in prompt
    assert "task_type" in prompt and "complexity" in prompt
    envelope = legacy_envelope(prompt)
    assert set(envelope) == {"request", "response_schema", "allowed_models", "allowed_providers"}
    assert envelope["request"]["message"] == "hello"


def test_gemma_adapter_allow_lists_are_explicit_system_constraints():
    fake = FakeGemma(response_json())
    adapter = GemmaRouterProvider(
        fake,
        model="router.gemma",
        allowed_models=["model.local", "model.alt"],
        allowed_providers=["provider.local"],
    )
    adapter.route(RouterRequest("hello"))

    prompt = fake.calls[0][1]
    assert "`model` field MUST be selected only" in prompt
    assert "`allowed_models` list: [\"model.local\", \"model.alt\"]" in prompt
    assert "`provider` field MUST be selected only" in prompt
    assert "`allowed_providers` list: [\"provider.local\"]" in prompt
    assert legacy_envelope(prompt)["allowed_models"] == ["model.local", "model.alt"]


def test_gemma_adapter_policy_supplies_dynamic_candidates_and_validates_decision():
    fake = FakeGemma(response_json())
    policy = FakeDecisionPolicy()
    adapter = GemmaRouterProvider(fake, model="router.gemma", decision_policy=policy)

    decision = adapter.route(RouterRequest("hello"))

    assert decision.model == "model.local"
    assert len(policy.requests) == 1
    assert policy.decisions == [(policy.requests[0], decision)]
    envelope = legacy_envelope(fake.calls[0][1])
    assert envelope["candidate_catalog"] == [
        {"model": "model.local", "provider": "provider.local"}
    ]
    assert envelope["allowed_models"] == ["model.local"]
    assert envelope["allowed_providers"] == ["provider.local"]


def test_gemma_adapter_policy_can_reject_route():
    class RejectingPolicy(FakeDecisionPolicy):
        def validate(self, request, decision):
            return False

    adapter = GemmaRouterProvider(
        FakeGemma(response_json()),
        model="router.gemma",
        decision_policy=RejectingPolicy(),
    )
    with pytest.raises(RouteParseError, match="rejected"):
        adapter.route(RouterRequest("hello"))


def test_gemma_adapter_accepts_one_complete_json_code_fence():
    fake = FakeGemma(f"```json\n{response_json()}\n```")
    adapter = GemmaRouterProvider(fake, model="router.gemma")
    decision = adapter.route(RouterRequest("hello"))
    assert decision.model == "model.local"


def test_gemma_adapter_rejects_non_json_or_unknown_fields():
    fake = FakeGemma("prefix {\"model\":\"m\"}")
    adapter = GemmaRouterProvider(fake, model="router.gemma")
    with pytest.raises(RouteParseError, match="invalid JSON"):
        adapter.route(RouterRequest("hello"))

    fake.response = json.dumps({"model": "m", "provider": "p", "unexpected": 1})
    with pytest.raises(RouteParseError, match="unknown field"):
        adapter.route(RouterRequest("hello"))


@pytest.mark.parametrize(
    "response",
    [
        f"{response_json()} trailing prose",
        f"```json\n{response_json()}\n``` trailing prose",
        f"```json\n{response_json()}\n```\n```json\n{response_json()}\n```",
        response_json().replace('"confidence": 0.95', '"confidence": NaN'),
        response_json().replace('"confidence": 0.95', '"confidence": 0.95, "extra": 1'),
        response_json().replace('"confidence": 0.95', '"confidence": 0.95, "model": "other"'),
    ],
)
def test_gemma_adapter_rejects_prose_duplicate_nan_and_unknown_fields(response):
    adapter = GemmaRouterProvider(FakeGemma(response), model="router.gemma")
    with pytest.raises(RouteParseError):
        adapter.route(RouterRequest("hello"))


def test_gemma_adapter_converts_transport_errors():
    class Broken:
        def chat(self, model, message, temperature=0.7):
            raise RuntimeError("offline")

    adapter = GemmaRouterProvider(Broken(), model="router.gemma")
    with pytest.raises(RouterTransportError, match="invocation failed"):
        adapter.route(RouterRequest("hello"))
