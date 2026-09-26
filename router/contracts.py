"""Side-effect-free contracts used by the Oratrice request router.

The router only produces a :class:`RouteDecision`; it never invokes a model,
starts a runtime, performs a health check, or executes a tool.  The contracts
in this module intentionally use only the Python standard library so that they
can be shared by frontends and infrastructure adapters.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import math
from types import MappingProxyType
from typing import Any


class RouterError(Exception):
    """Base error for route validation and selection failures."""


class RouteValidationError(RouterError, ValueError):
    """Raised when a request or decision is malformed."""


class RouteParseError(RouteValidationError):
    """Raised when a model response is not a valid route document."""


class RouteNotFoundError(RouterError):
    """Raised when no configured route can satisfy a request."""


class RouteCapabilityError(RouterError):
    """Raised when a route cannot satisfy requested capabilities."""


class RouterTransportError(RouterError):
    """Raised when an injected routing-model transport fails."""


def _text(value: Any, name: str, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        requirement = "" if required else " or null"
        raise RouteValidationError(f"{name} must be a non-empty string{requirement}")
    return value.strip()


def _bool(value: Any, name: str) -> bool:
    # bool is deliberately not coerced from strings/integers.  A model that
    # emits ``\"false\"`` is not returning a trustworthy structured decision.
    if not isinstance(value, bool):
        raise RouteValidationError(f"{name} must be a boolean")
    return value


def _capabilities(value: Any, name: str = "capabilities") -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise RouteValidationError(f"{name} must be an array of strings")
    result: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise RouteValidationError(f"{name}[{index}] must be a non-empty string")
        item = item.strip()
        if item not in seen:
            result.append(item)
            seen.add(item)
    return tuple(result)


def _confidence(value: Any) -> float:
    # ``bool`` is an ``int`` subclass, so reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RouteValidationError("confidence must be a number between 0 and 1")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise RouteValidationError("confidence must be a number between 0 and 1")
    return result


def _complexity(value: Any) -> str:
    """Validate the bounded complexity value emitted by a router."""

    if not isinstance(value, str) or not value.strip():
        raise RouteValidationError("complexity must be one of: low, medium, high")
    result = value.strip()
    if result not in {"low", "medium", "high"}:
        raise RouteValidationError("complexity must be one of: low, medium, high")
    return result


def _metadata(value: Any) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise RouteValidationError("metadata must be an object")
    return MappingProxyType(dict(value))


@dataclass(frozen=True, slots=True, init=False)
class RouteDecision:
    """A complete, structured answer from a router.

    ``model`` and ``provider`` are opaque IDs supplied by configuration or a
    composition root.  No provider/model names are embedded in this class.
    Capability flags use the explicit ``requires_*`` spelling in the wire
    contract.  Common aliases (``vision``, ``needs_vision``, and so on) are
    accepted by the constructor and exposed as read-only properties for
    compatibility with callers that use shorter names.
    """

    model: str
    provider: str
    task_type: str
    complexity: str
    capabilities: tuple[str, ...]
    requires_vision: bool
    requires_network: bool
    requires_tools: bool
    reason: str
    confidence: float

    def __init__(
        self,
        model: str | None = None,
        provider: str | None = None,
        capabilities: Sequence[str] | None = None,
        requires_vision: bool = False,
        requires_network: bool = False,
        requires_tools: bool = False,
        reason: str = "",
        confidence: float = 1.0,
        *,
        model_id: str | None = None,
        provider_id: str | None = None,
        task_type: str = "general",
        complexity: str = "medium",
        task: str | None = None,
        difficulty: str | None = None,
        vision: bool | None = None,
        network: bool | None = None,
        tools: bool | None = None,
        needs_vision: bool | None = None,
        needs_network: bool | None = None,
        needs_tools: bool | None = None,
        use_vision: bool | None = None,
        use_network: bool | None = None,
        use_tools: bool | None = None,
        supports_vision: bool | None = None,
        supports_network: bool | None = None,
        supports_tools: bool | None = None,
    ) -> None:
        if model is None:
            model = model_id
        elif model_id is not None and model != model_id:
            raise RouteValidationError("model and model_id disagree")
        if provider is None:
            provider = provider_id
        elif provider_id is not None and provider != provider_id:
            raise RouteValidationError("provider and provider_id disagree")

        if task is not None:
            if task_type != "general" and task_type != task:
                raise RouteValidationError("task_type and task disagree")
            task_type = task
        if difficulty is not None:
            if complexity != "medium" and complexity != difficulty:
                raise RouteValidationError("complexity and difficulty disagree")
            complexity = difficulty

        requires_vision = self._choose_bool(
            requires_vision,
            (vision, needs_vision, use_vision),
            "requires_vision",
        )
        requires_network = self._choose_bool(
            requires_network,
            (network, needs_network, use_network),
            "requires_network",
        )
        requires_tools = self._choose_bool(
            requires_tools,
            (tools, needs_tools, use_tools),
            "requires_tools",
        )
        requires_vision = self._choose_bool(
            requires_vision,
            (supports_vision,),
            "requires_vision",
        )
        requires_network = self._choose_bool(
            requires_network,
            (supports_network,),
            "requires_network",
        )
        requires_tools = self._choose_bool(
            requires_tools,
            (supports_tools,),
            "requires_tools",
        )

        model = _text(model, "model")
        provider = _text(provider, "provider")
        task_type = _text(task_type, "task_type")
        complexity = _complexity(complexity)
        caps = _capabilities(capabilities)
        if not isinstance(reason, str):
            raise RouteValidationError("reason must be a string")
        reason = reason.strip()
        score = _confidence(confidence)

        object.__setattr__(self, "model", model)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "task_type", task_type)
        object.__setattr__(self, "complexity", complexity)
        object.__setattr__(self, "capabilities", caps)
        object.__setattr__(self, "requires_vision", requires_vision)
        object.__setattr__(self, "requires_network", requires_network)
        object.__setattr__(self, "requires_tools", requires_tools)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "confidence", score)

    @staticmethod
    def _choose_bool(primary: Any, aliases: Sequence[Any], name: str) -> bool:
        provided = [value for value in aliases if value is not None]
        if provided:
            for value in provided:
                _bool(value, name)
            if any(value != provided[0] for value in provided[1:]):
                raise RouteValidationError(f"conflicting aliases for {name}")
            if primary is not False and primary != provided[0]:
                raise RouteValidationError(f"conflicting aliases for {name}")
            primary = provided[0]
        return _bool(primary, name)

    # Short aliases are useful at the facade boundary and do not alter the
    # canonical serialized representation.
    @property
    def model_id(self) -> str:
        return self.model

    @property
    def provider_id(self) -> str:
        return self.provider

    @property
    def task(self) -> str:
        """Backward-compatible short alias for ``task_type``."""

        return self.task_type

    @property
    def difficulty(self) -> str:
        """Backward-compatible alias for ``complexity``."""

        return self.complexity

    @property
    def vision(self) -> bool:
        return self.requires_vision

    @property
    def network(self) -> bool:
        return self.requires_network

    @property
    def tools(self) -> bool:
        return self.requires_tools

    @property
    def needs_vision(self) -> bool:
        return self.requires_vision

    @property
    def needs_network(self) -> bool:
        return self.requires_network

    @property
    def needs_tools(self) -> bool:
        return self.requires_tools

    @property
    def use_vision(self) -> bool:
        return self.requires_vision

    @property
    def use_network(self) -> bool:
        return self.requires_network

    @property
    def use_tools(self) -> bool:
        return self.requires_tools

    def to_dict(self) -> dict[str, Any]:
        """Return the strict JSON-compatible route representation."""

        return {
            "model": self.model,
            "provider": self.provider,
            "task_type": self.task_type,
            "complexity": self.complexity,
            "capabilities": list(self.capabilities),
            "requires_vision": self.requires_vision,
            "requires_network": self.requires_network,
            "requires_tools": self.requires_tools,
            "reason": self.reason,
            "confidence": self.confidence,
        }

    as_dict = to_dict

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RouteDecision":
        """Validate a mapping returned by a routing model.

        Unknown keys and conflicting aliases are rejected.  Optional fields
        have conservative defaults so a model may omit a capability flag, but
        values that are present must have the exact expected type.
        """

        if not isinstance(value, Mapping):
            raise RouteParseError("route decision must be a JSON object")

        aliases = {
            "model_id": "model",
            "provider_id": "provider",
            "task": "task_type",
            "difficulty": "complexity",
            "vision": "requires_vision",
            "needs_vision": "requires_vision",
            "use_vision": "requires_vision",
            "supports_vision": "requires_vision",
            "network": "requires_network",
            "needs_network": "requires_network",
            "use_network": "requires_network",
            "supports_network": "requires_network",
            "tools": "requires_tools",
            "needs_tools": "requires_tools",
            "use_tools": "requires_tools",
            "supports_tools": "requires_tools",
        }
        allowed = {
            "model",
            "provider",
            "task_type",
            "complexity",
            "capabilities",
            "requires_vision",
            "requires_network",
            "requires_tools",
            "reason",
            "confidence",
            *aliases,
        }
        unknown = [key for key in value if key not in allowed]
        if unknown:
            raise RouteParseError(f"route decision contains unknown field(s): {', '.join(map(str, unknown))}")

        canonical: dict[str, Any] = {}
        for key, item in value.items():
            target = aliases.get(key, key)
            if target in canonical and canonical[target] != item:
                raise RouteParseError(f"conflicting values for route field {target!r}")
            canonical[target] = item

        try:
            return cls(
                model=canonical.get("model"),
                provider=canonical.get("provider"),
                task_type=canonical.get("task_type", "general"),
                complexity=canonical.get("complexity", "medium"),
                capabilities=canonical.get("capabilities", ()),
                requires_vision=canonical.get("requires_vision", False),
                requires_network=canonical.get("requires_network", False),
                requires_tools=canonical.get("requires_tools", False),
                reason=canonical.get("reason", ""),
                confidence=canonical.get("confidence", 1.0),
            )
        except RouteValidationError as exc:
            raise RouteParseError(str(exc)) from exc

    from_dict = from_mapping


@dataclass(frozen=True, slots=True, init=False)
class RouterRequest:
    """Input to a router; it contains intent metadata, not a user answer."""

    message: str
    model: str | None
    provider: str | None
    capabilities: tuple[str, ...]
    requires_vision: bool
    requires_network: bool
    requires_tools: bool
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        message: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        capabilities: Sequence[str] | None = None,
        requires_vision: bool = False,
        requires_network: bool = False,
        requires_tools: bool = False,
        metadata: Mapping[str, Any] | None = None,
        *,
        text: str | None = None,
        model_id: str | None = None,
        provider_id: str | None = None,
        vision: bool | None = None,
        network: bool | None = None,
        tools: bool | None = None,
        needs_vision: bool | None = None,
        needs_network: bool | None = None,
        needs_tools: bool | None = None,
        supports_vision: bool | None = None,
        supports_network: bool | None = None,
        supports_tools: bool | None = None,
    ) -> None:
        if message is None:
            message = text
        elif text is not None and message != text:
            raise RouteValidationError("message and text disagree")
        if message is None:
            message = ""
        if not isinstance(message, str):
            raise RouteValidationError("message must be a string")
        if model is None:
            model = model_id
        elif model_id is not None and model != model_id:
            raise RouteValidationError("model and model_id disagree")
        if provider is None:
            provider = provider_id
        elif provider_id is not None and provider != provider_id:
            raise RouteValidationError("provider and provider_id disagree")
        model = _text(model, "model", required=False)
        provider = _text(provider, "provider", required=False)
        requires_vision = RouteDecision._choose_bool(
            requires_vision,
            (vision, needs_vision),
            "requires_vision",
        )
        requires_network = RouteDecision._choose_bool(
            requires_network,
            (network, needs_network),
            "requires_network",
        )
        requires_tools = RouteDecision._choose_bool(
            requires_tools,
            (tools, needs_tools),
            "requires_tools",
        )
        requires_vision = RouteDecision._choose_bool(
            requires_vision,
            (supports_vision,),
            "requires_vision",
        )
        requires_network = RouteDecision._choose_bool(
            requires_network,
            (supports_network,),
            "requires_network",
        )
        requires_tools = RouteDecision._choose_bool(
            requires_tools,
            (supports_tools,),
            "requires_tools",
        )
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "capabilities", _capabilities(capabilities))
        object.__setattr__(self, "requires_vision", requires_vision)
        object.__setattr__(self, "requires_network", requires_network)
        object.__setattr__(self, "requires_tools", requires_tools)
        object.__setattr__(self, "metadata", _metadata(metadata))

    @property
    def text(self) -> str:
        return self.message

    @property
    def model_id(self) -> str | None:
        return self.model

    @property
    def provider_id(self) -> str | None:
        return self.provider

    @property
    def vision(self) -> bool:
        return self.requires_vision

    @property
    def network(self) -> bool:
        return self.requires_network

    @property
    def tools(self) -> bool:
        return self.requires_tools

    @property
    def needs_vision(self) -> bool:
        return self.requires_vision

    @property
    def needs_network(self) -> bool:
        return self.requires_network

    @property
    def needs_tools(self) -> bool:
        return self.requires_tools

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": self.message,
            "model": self.model,
            "provider": self.provider,
            "capabilities": list(self.capabilities),
            "requires_vision": self.requires_vision,
            "requires_network": self.requires_network,
            "requires_tools": self.requires_tools,
            "metadata": dict(self.metadata),
        }

    as_dict = to_dict


def coerce_request(value: RouterRequest | Mapping[str, Any]) -> RouterRequest:
    """Convert a request mapping while keeping the public router API strict."""

    if isinstance(value, RouterRequest):
        return value
    if isinstance(value, Mapping):
        try:
            return RouterRequest(**dict(value))
        except (TypeError, RouteValidationError) as exc:
            raise RouteValidationError(f"invalid router request: {exc}") from exc
    raise RouteValidationError("router request must be RouterRequest or an object")


__all__ = [
    "RouteCapabilityError",
    "RouteDecision",
    "RouteNotFoundError",
    "RouteParseError",
    "RouteValidationError",
    "RouterError",
    "RouterRequest",
    "RouterTransportError",
    "coerce_request",
]
