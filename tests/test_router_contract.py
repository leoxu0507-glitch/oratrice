from __future__ import annotations

import pytest

from router import RouteDecision, RouteParseError, RouterRequest


def test_decision_is_structured_and_exposes_aliases():
    decision = RouteDecision(
        model="model.local",
        provider="provider.local",
        capabilities=("chat", "vision"),
        vision=True,
        reason="local model supports the request",
        confidence=0.8,
    )
    assert decision.model_id == "model.local"
    assert decision.provider_id == "provider.local"
    assert decision.task_type == "general"
    assert decision.task == "general"
    assert decision.complexity == "medium"
    assert decision.difficulty == "medium"
    assert decision.requires_vision is True
    assert decision.vision is True
    assert decision.to_dict()["requires_vision"] is True


def test_decision_task_fields_default_and_alias_roundtrip():
    legacy = RouteDecision.from_mapping({"model": "m", "provider": "p"})
    assert legacy.task_type == "general"
    assert legacy.complexity == "medium"

    aliased = RouteDecision.from_mapping(
        {"model": "m", "provider": "p", "task": "summarize", "difficulty": "low"}
    )
    assert aliased.task_type == "summarize"
    assert aliased.complexity == "low"
    assert aliased.to_dict()["task_type"] == "summarize"
    assert aliased.to_dict()["complexity"] == "low"

    with pytest.raises(RouteParseError, match="complexity"):
        RouteDecision.from_mapping({"model": "m", "provider": "p", "complexity": "extreme"})
    with pytest.raises(RouteParseError, match="task_type"):
        RouteDecision.from_mapping({"model": "m", "provider": "p", "task_type": ""})


def test_decision_rejects_unknown_fields_and_bad_confidence():
    with pytest.raises(RouteParseError, match="unknown field"):
        RouteDecision.from_mapping({"model": "m", "provider": "p", "answer": "no"})
    with pytest.raises(RouteParseError, match="between 0 and 1"):
        RouteDecision.from_mapping({"model": "m", "provider": "p", "confidence": 2})


def test_request_accepts_text_alias():
    request = RouterRequest(text="hello", model_id="model.local", network=True)
    assert request.message == "hello"
    assert request.text == "hello"
    assert request.model == "model.local"
    assert request.requires_network is True
