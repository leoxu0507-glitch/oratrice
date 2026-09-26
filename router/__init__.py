"""Oratrice routing contracts and adapters.

Only route selection lives here.  Provider invocation, lifecycle management,
network access, and tool execution belong to other layers.
"""

from .base import BaseRouter, DeterministicRouter, Router, RouterProtocol, StaticRouter
from .policy import RoutePolicyError, RoutingCandidate, RoutingPolicy
from .contracts import (
    RouteCapabilityError,
    RouteDecision,
    RouteNotFoundError,
    RouteParseError,
    RouteValidationError,
    RouterError,
    RouterRequest,
    RouterTransportError,
    coerce_request,
)
from .gemma import (
    GemmaRouter,
    GemmaRouterAdapter,
    GemmaRouterProvider,
    ROUTE_DECISION_SCHEMA,
    RoutingModelClient,
)

__all__ = [
    "BaseRouter",
    "DeterministicRouter",
    "GemmaRouter",
    "GemmaRouterAdapter",
    "GemmaRouterProvider",
    "ROUTE_DECISION_SCHEMA",
    "RouteCapabilityError",
    "RouteDecision",
    "RouteNotFoundError",
    "RouteParseError",
    "RouteValidationError",
    "Router",
    "RouterError",
    "RouterProtocol",
    "RouterRequest",
    "RouterTransportError",
    "RoutingModelClient",
    "StaticRouter",
    "RoutePolicyError",
    "RoutingCandidate",
    "RoutingPolicy",
    "coerce_request",
]

