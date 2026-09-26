"""Configuration-driven, side-effect-free route policy.

The policy converts a declarative candidate catalogue into deterministic
validation for :class:`router.contracts.RouteDecision` objects.  It deliberately
knows nothing about provider transports, runtime lifecycle, or network I/O.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .contracts import (
    RouteCapabilityError,
    RouteDecision,
    RouterError,
    RouterRequest,
    coerce_request,
)


class RoutePolicyError(RouteCapabilityError):
    """A configured route candidate cannot satisfy a request or decision."""



def _error(message: str) -> RoutePolicyError:
    return RoutePolicyError(message)



def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(f"{label} must be a non-empty string")
    return value.strip()



def _string_tuple(value: Any, label: str) -> tuple[str, ...]:
    """Validate a sequence of opaque IDs/capabilities and freeze it."""

    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _error(f"{label} must be an array of strings")
    result: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        item = _text(item, f"{label}[{index}]")
        if item in seen:
            raise _error(f"{label} contains duplicate value {item!r}")
        seen.add(item)
        result.append(item)
    return tuple(result)



def _priority(value: Any) -> int:
    # ``bool`` is an ``int`` subclass, but is not a useful ordering value.
    if isinstance(value, bool) or not isinstance(value, int):
        raise _error("priority must be an integer")
    return value



def _strict_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise _error(f"{label} must be a boolean")
    return value


_COMPLEXITIES = frozenset({"low", "medium", "high"})


def _complexity_tuple(value: Any, label: str) -> tuple[str, ...]:
    result = _string_tuple(value, label)
    invalid = [item for item in result if item not in _COMPLEXITIES]
    if invalid:
        raise _error(f"{label} values must be one of: low, medium, high")
    return result


@dataclass(frozen=True, slots=True)
class RoutingCandidate:
    """One opaque model/provider pair in a routing catalogue.

    ``task_types``, ``complexities``, and ``capabilities`` are exact string
    labels supplied by configuration.  Empty task/complexity constraints are
    wildcards.  A candidate marked ``requires_cloud_opt_in`` is available only
    when the request metadata contains the policy's opt-in key with the exact
    boolean value ``True``.
    """

    id: str
    model: str
    provider: str
    task_types: tuple[str, ...] = ()
    complexities: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    priority: int = 0
    requires_cloud_opt_in: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _text(self.id, "candidate.id"))
        object.__setattr__(self, "model", _text(self.model, "candidate.model"))
        object.__setattr__(self, "provider", _text(self.provider, "candidate.provider"))
        object.__setattr__(self, "task_types", _string_tuple(self.task_types, "candidate.task_types"))
        object.__setattr__(self, "complexities", _complexity_tuple(self.complexities, "candidate.complexities"))
        object.__setattr__(self, "capabilities", _string_tuple(self.capabilities, "candidate.capabilities"))
        object.__setattr__(self, "priority", _priority(self.priority))
        object.__setattr__(
            self,
            "requires_cloud_opt_in",
            _strict_bool(self.requires_cloud_opt_in, "candidate.requires_cloud_opt_in"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe, detached representation for routing prompts."""

        return {
            "id": self.id,
            "model": self.model,
            "provider": self.provider,
            "task_types": list(self.task_types),
            "complexities": list(self.complexities),
            "capabilities": list(self.capabilities),
            "priority": self.priority,
            "requires_cloud_opt_in": self.requires_cloud_opt_in,
        }

    as_dict = to_dict


_POLICY_KEYS = frozenset({"candidates", "cloud_opt_in_key"})
_CANDIDATE_KEYS = frozenset(
    {
        "id",
        "model",
        "provider",
        "task_types",
        "complexities",
        "capabilities",
        "priority",
        "requires_cloud_opt_in",
    }
)


@dataclass(frozen=True, slots=True)
class RoutingPolicy:
    """Immutable catalogue and deterministic route-policy evaluator."""

    candidates: tuple[RoutingCandidate, ...]
    cloud_opt_in_key: str = "allow_cloud"

    def __post_init__(self) -> None:
        if isinstance(self.candidates, (str, bytes)) or not isinstance(self.candidates, Sequence):
            raise _error("candidates must be an array of RoutingCandidate objects")
        candidates: list[RoutingCandidate] = []
        seen_ids: set[str] = set()
        for index, candidate in enumerate(self.candidates):
            if not isinstance(candidate, RoutingCandidate):
                raise _error(f"candidates[{index}] must be a RoutingCandidate")
            if candidate.id in seen_ids:
                raise _error(f"duplicate candidate id {candidate.id!r}")
            seen_ids.add(candidate.id)
            candidates.append(candidate)
        if not candidates:
            raise _error("candidates must contain at least one candidate")
        object.__setattr__(self, "candidates", tuple(candidates))
        object.__setattr__(self, "cloud_opt_in_key", _text(self.cloud_opt_in_key, "cloud_opt_in_key"))

    @property
    def catalog(self) -> tuple[RoutingCandidate, ...]:
        """Alias useful to composition roots that call this a candidate catalog."""

        return self.candidates

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RoutingPolicy":
        """Parse and strictly validate a policy mapping.

        The accepted shape is ``{"candidates": [{...}],
        "cloud_opt_in_key": "allow_cloud"}``.  The key is optional and
        defaults to ``allow_cloud``; candidate list fields default to empty
        wildcards, priority defaults to zero, and cloud opt-in defaults false.
        Unknown keys and malformed values are rejected with ``RoutePolicyError``.
        """

        if not isinstance(value, Mapping):
            raise _error("routing policy must be an object")
        unknown = [key for key in value if key not in _POLICY_KEYS]
        if unknown:
            raise _error(
                "routing policy contains unknown field(s): "
                + ", ".join(map(str, unknown))
            )
        raw_candidates = value.get("candidates")
        if isinstance(raw_candidates, (str, bytes)) or not isinstance(raw_candidates, Sequence):
            raise _error("candidates must be an array of objects")

        candidates: list[RoutingCandidate] = []
        for index, raw in enumerate(raw_candidates):
            if isinstance(raw, RoutingCandidate):
                candidates.append(raw)
                continue
            if not isinstance(raw, Mapping):
                raise _error(f"candidates[{index}] must be an object")
            unknown_candidate = [key for key in raw if key not in _CANDIDATE_KEYS]
            if unknown_candidate:
                raise _error(
                    f"candidates[{index}] contains unknown field(s): "
                    + ", ".join(map(str, unknown_candidate))
                )
            missing = [key for key in ("id", "model", "provider") if key not in raw]
            if missing:
                raise _error(
                    f"candidates[{index}] is missing required field(s): "
                    + ", ".join(missing)
                )
            candidates.append(
                RoutingCandidate(
                    id=raw["id"],
                    model=raw["model"],
                    provider=raw["provider"],
                    task_types=raw.get("task_types", ()),
                    complexities=raw.get("complexities", ()),
                    capabilities=raw.get("capabilities", ()),
                    priority=raw.get("priority", 0),
                    requires_cloud_opt_in=raw.get("requires_cloud_opt_in", False),
                )
            )
        key = value.get("cloud_opt_in_key", "allow_cloud")
        return cls(candidates=tuple(candidates), cloud_opt_in_key=key)

    @staticmethod
    def _request_metadata(request: RouterRequest) -> Mapping[str, Any]:
        metadata = request.metadata
        if not isinstance(metadata, Mapping):
            # RouterRequest normally guarantees this; retain the policy's
            # RouterError-only boundary if a foreign implementation is passed.
            raise _error("request metadata must be an object")
        return metadata

    def _cloud_opted_in(self, request: RouterRequest) -> bool:
        # Deliberately require the exact boolean True.  Values such as "true",
        # 1, and non-empty objects must not silently permit cloud traffic.
        return self._request_metadata(request).get(self.cloud_opt_in_key) is True

    def prompt_candidates(
        self, request: RouterRequest | Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        """Return a detached JSON-safe candidate directory for a request."""

        request = coerce_request(request)
        opted_in = self._cloud_opted_in(request)
        return [
            candidate.to_dict()
            for candidate in self.candidates
            if not candidate.requires_cloud_opt_in or opted_in
        ]

    @staticmethod
    def _decision_label(decision: RouteDecision, key: str) -> str:
        value = getattr(decision, key, None)
        if not isinstance(value, str) or not value.strip():
            raise _error(f"decision {key!r} must be a non-empty string")
        value = value.strip()
        if key == "complexity" and value not in _COMPLEXITIES:
            raise _error("decision complexity must be one of: low, medium, high")
        return value

    @staticmethod
    def _supports_flag(capabilities: set[str], flag: str) -> bool:
        # The request/decision contracts expose booleans while configuration
        # exposes opaque capability labels.  These three canonical labels are
        # the only translation performed by the policy.
        return flag in capabilities

    def _matches_request(
        self,
        request: RouterRequest,
        decision: RouteDecision,
        candidate: RoutingCandidate,
    ) -> bool:
        if request.model is not None and request.model != candidate.model:
            return False
        if request.provider is not None and request.provider != candidate.provider:
            return False
        if candidate.requires_cloud_opt_in and not self._cloud_opted_in(request):
            return False

        candidate_capabilities = set(candidate.capabilities)
        if not set(request.capabilities).issubset(candidate_capabilities):
            return False
        for required, capability in (
            (request.requires_vision, "vision"),
            (request.requires_network, "network"),
            (request.requires_tools, "tools"),
        ):
            if required and not self._supports_flag(candidate_capabilities, capability):
                return False

        # Task/complexity are classifier decision fields, not request metadata.
        # RouteDecision defaults (general/medium) keep ordinary chat requests
        # verifiable even when the caller supplied no metadata.
        task_type = self._decision_label(decision, "task_type")
        if candidate.task_types and task_type not in candidate.task_types:
            return False
        complexity = self._decision_label(decision, "complexity")
        if candidate.complexities and complexity not in candidate.complexities:
            return False
        return True
    @staticmethod
    def _coerce_decision(value: RouteDecision | Mapping[str, Any]) -> RouteDecision:
        if isinstance(value, RouteDecision):
            return value
        if isinstance(value, Mapping):
            try:
                return RouteDecision.from_mapping(value)
            except RouterError:
                raise
            except Exception as exc:
                raise _error(f"invalid route decision: {exc}") from exc
        raise _error("decision must be a RouteDecision or object")

    def validate(
        self,
        request: RouterRequest | Mapping[str, Any],
        decision: RouteDecision | Mapping[str, Any],
    ) -> RouteDecision:
        """Validate a decision against the highest-priority matching candidate."""

        request = coerce_request(request)
        decision = self._coerce_decision(decision)
        if not any(
            candidate.model == decision.model and candidate.provider == decision.provider
            for candidate in self.candidates
        ):
            raise _error("decision model/provider pair is not configured")
        matching = [
            candidate for candidate in self.candidates if self._matches_request(request, decision, candidate)
        ]
        if not matching:
            raise _error("no configured candidate matches the request")

        # Stable max preserves configuration order for equal priorities.
        selected = max(matching, key=lambda candidate: candidate.priority)
        if (decision.model, decision.provider) != (selected.model, selected.provider):
            raise _error(
                "decision does not select the highest-priority candidate "
                f"{selected.id!r}"
            )

        # A request's hard capability requirements may never be weakened by a
        # classifier response, even if the selected candidate supports them.
        for required, actual, label in (
            (request.requires_vision, decision.requires_vision, "vision"),
            (request.requires_network, decision.requires_network, "network"),
            (request.requires_tools, decision.requires_tools, "tools"),
        ):
            if required and not actual:
                raise _error(f"decision weakens request requires_{label}")

        selected_capabilities = set(selected.capabilities)
        if not set(request.capabilities).issubset(selected_capabilities):
            raise _error("selected candidate does not cover request capabilities")
        if not set(decision.capabilities).issubset(selected_capabilities):
            raise _error("decision capabilities are not covered by selected candidate")
        for actual, label in (
            (decision.requires_vision, "vision"),
            (decision.requires_network, "network"),
            (decision.requires_tools, "tools"),
        ):
            if actual and not self._supports_flag(selected_capabilities, label):
                raise _error(f"decision requires unsupported capability {label!r}")

        # Cloud gating is enforced while computing matching candidates, so this
        # branch can return only a route that was explicitly opted into.
        return decision


__all__ = ["RoutePolicyError", "RoutingCandidate", "RoutingPolicy"]




