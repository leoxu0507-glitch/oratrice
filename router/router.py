"""Compatibility import surface for the router port and contracts."""

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
)

__all__ = [
    "BaseRouter",
    "DeterministicRouter",
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
    "StaticRouter",
    "RoutePolicyError",
    "RoutingCandidate",
    "RoutingPolicy",
]

