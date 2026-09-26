from __future__ import annotations

import pytest

from router import (
    RouteCapabilityError,
    RouteDecision,
    RouteNotFoundError,
    RouterRequest,
    StaticRouter,
)


def test_static_router_uses_injected_local_first_default():
    decision = RouteDecision("model.local", "provider.local", reason="configured")
    router = StaticRouter(default=decision, local_providers={"provider.local"})
    assert router.route(RouterRequest("hello")) == decision


def test_static_router_selects_explicit_model_without_calling_a_provider():
    local = RouteDecision("model.local", "provider.local")
    second = RouteDecision("model.second", "provider.second")
    router = StaticRouter(
        routes={"model.second": second},
        default=local,
    )
    assert router.route(RouterRequest("hello", model="model.second")) == second


def test_static_router_rejects_missing_route_and_capability():
    router = StaticRouter(default=RouteDecision("m", "p"))
    with pytest.raises(RouteNotFoundError):
        router.route(RouterRequest("hello", model="other"))
    with pytest.raises(RouteCapabilityError):
        router.route(RouterRequest("image", requires_vision=True))


def test_cloud_fallback_requires_explicit_opt_in():
    local = RouteDecision("m.local", "p.local")
    cloud = RouteDecision("m.cloud", "p.cloud")
    router = StaticRouter(
        default=local,
        fallback=cloud,
        allow_cloud_fallback=False,
        cloud_providers={"p.cloud"},
    )
    with pytest.raises(RouteNotFoundError):
        router.route(RouterRequest("hello", model="m.cloud"))
