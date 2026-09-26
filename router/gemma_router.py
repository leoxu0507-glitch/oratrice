"""Compatibility import surface for the Gemma routing adapter."""

from .gemma import (
    GemmaRouter,
    GemmaRouterAdapter,
    GemmaRouterProvider,
    ROUTE_DECISION_SCHEMA,
    RoutingModelClient,
)

__all__ = [
    "GemmaRouter",
    "GemmaRouterAdapter",
    "GemmaRouterProvider",
    "ROUTE_DECISION_SCHEMA",
    "RoutingModelClient",
]
