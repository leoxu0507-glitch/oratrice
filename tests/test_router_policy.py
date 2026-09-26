from __future__ import annotations

import json

import pytest

from router import (
    RouteCapabilityError,
    RouteDecision,
    RoutePolicyError,
    RouterRequest,
    RoutingCandidate,
    RoutingPolicy,
)


def _policy() -> RoutingPolicy:
    return RoutingPolicy.from_mapping(
        {
            "candidates": [
                {
                    "id": "local-text",
                    "model": "model.local",
                    "provider": "provider.local",
                    "task_types": ["general"],
                    "complexities": ["low", "medium", "high"],
                    "capabilities": ["chat", "vision", "network", "tools"],
                    "priority": 10,
                    "requires_cloud_opt_in": False,
                },
                {
                    "id": "cloud-reasoning",
                    "model": "model.cloud",
                    "provider": "provider.cloud",
                    "task_types": ["general"],
                    "complexities": ["high"],
                    "capabilities": ["chat", "reasoning"],
                    "priority": 20,
                    "requires_cloud_opt_in": True,
                },
            ]
        }
    )


def test_policy_is_immutable_and_prompt_catalog_is_json_safe():
    policy = _policy()
    assert isinstance(policy.candidates, tuple)
    assert policy.catalog == policy.candidates
    request = RouterRequest("hello")
    local_only = policy.prompt_candidates(request)
    assert [item["id"] for item in local_only] == ["local-text"]
    assert json.loads(json.dumps(local_only))[0]["capabilities"] == [
        "chat",
        "vision",
        "network",
        "tools",
    ]
    # Opt-in is exact: a truthy string must not expose cloud candidates.
    assert len(policy.prompt_candidates(RouterRequest("hello", metadata={"allow_cloud": "true"}))) == 1
    with_cloud = policy.prompt_candidates(RouterRequest("hello", metadata={"allow_cloud": True}))
    assert [item["id"] for item in with_cloud] == ["local-text", "cloud-reasoning"]
    with pytest.raises((AttributeError, TypeError)):
        policy.candidates += (RoutingCandidate("x", "m", "p"),)


def test_validate_selects_highest_priority_and_matches_decision_intent():
    request = RouterRequest("solve this", capabilities=["chat"], metadata={"allow_cloud": True})
    decision = RouteDecision(
        model="model.cloud",
        provider="provider.cloud",
        task="general",
        difficulty="high",
        capabilities=["chat"],
        reason="configured policy",
    )
    assert _policy().validate(request, decision) is decision


def test_validate_rejects_lower_priority_or_unknown_pair():
    request = RouterRequest("hello", capabilities=["chat"], metadata={"allow_cloud": True})
    local = RouteDecision("model.local", "provider.local", task="general", difficulty="high", capabilities=["chat"])
    with pytest.raises(RoutePolicyError, match="highest-priority"):
        _policy().validate(request, local)
    unknown = RouteDecision("model.unknown", "provider.unknown", task="general", difficulty="medium")
    with pytest.raises(RoutePolicyError):
        _policy().validate(RouterRequest("hello"), unknown)


def test_validate_enforces_hard_flags_and_capability_coverage():
    policy = _policy()
    request = RouterRequest("image", requires_vision=True, capabilities=["chat"])
    weakened = RouteDecision(
        "model.local",
        "provider.local",
        task="general",
        difficulty="medium",
        capabilities=["chat"],
        requires_vision=False,
    )
    with pytest.raises(RoutePolicyError, match="weakens"):
        policy.validate(request, weakened)

    unsupported = RouteDecision(
        "model.local",
        "provider.local",
        task="general",
        difficulty="medium",
        capabilities=["chat", "not-configured"],
    )
    with pytest.raises(RoutePolicyError, match="covered"):
        policy.validate(RouterRequest("hello", capabilities=["chat"]), unsupported)


def test_cloud_requires_explicit_opt_in_and_task_complexity_is_strict():
    policy = _policy()
    cloud = RouteDecision(
        "model.cloud",
        "provider.cloud",
        task="general",
        difficulty="high",
        capabilities=["chat"],
    )
    with pytest.raises(RoutePolicyError):
        policy.validate(RouterRequest("hello"), cloud)

    mismatched = RouteDecision(
        "model.cloud",
        "provider.cloud",
        task="general",
        difficulty="medium",
        capabilities=["chat"],
    )
    with pytest.raises(RoutePolicyError):
        policy.validate(RouterRequest("hello", metadata={"allow_cloud": True}), mismatched)


@pytest.mark.parametrize(
    "candidate, message",
    [
        ({"id": "x", "model": "m", "provider": "p", "priority": True}, "priority"),
        ({"id": "x", "model": "m", "provider": "p", "complexities": ["extreme"]}, "complexities"),
        ({"id": "x", "model": "m", "provider": "p", "requires_cloud_opt_in": "yes"}, "requires_cloud_opt_in"),
        ({"id": "x", "model": "m", "provider": "p", "unknown": 1}, "unknown"),
    ],
)
def test_from_mapping_rejects_malformed_candidates(candidate, message):
    with pytest.raises(RoutePolicyError, match=message):
        RoutingPolicy.from_mapping({"candidates": [candidate]})


def test_route_policy_error_preserves_router_capability_error_contract():
    assert issubclass(RoutePolicyError, RouteCapabilityError)



