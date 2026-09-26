"""Gemma routing-model adapter with strict JSON decision validation.

The adapter receives an injected client/transport.  It does not import an HTTP
library, inspect provider health, start a runtime, or answer the user's
message.  Its sole model call asks the configured Gemma model for a route
document and converts that document into :class:`RouteDecision`.
"""

from __future__ import annotations

import inspect
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from .base import Router
from .contracts import (
    RouteDecision,
    RouteParseError,
    RouterRequest,
    RouterTransportError,
    coerce_request,
)


@runtime_checkable
class RoutingModelClient(Protocol):
    """Optional client port used by :class:`GemmaRouterProvider`.

    Implementations may expose either ``complete`` or ``chat``.  The concrete
    provider/SDK is injected by the composition root, keeping this module free
    of network and model-specific dependencies.
    """

    def complete(self, **kwargs: Any) -> Any:
        ...


ROUTE_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
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
    ],
    "properties": {
        "model": {"type": "string", "minLength": 1},
        "provider": {"type": "string", "minLength": 1},
        "task_type": {"type": "string", "minLength": 1},
        "complexity": {"type": "string", "enum": ["low", "medium", "high"]},
        "capabilities": {"type": "array", "items": {"type": "string"}},
        "requires_vision": {"type": "boolean"},
        "requires_network": {"type": "boolean"},
        "requires_tools": {"type": "boolean"},
        "reason": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}


SYSTEM_PROMPT = (
    "You are a routing classifier. Classify the request's task_type and "
    "complexity, then return exactly one JSON object matching the provided "
    "route-decision schema. Make a routing decision only: do not answer, "
    "rewrite, or execute the user's request. Use only the configured model "
    "and provider IDs."
)


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON number {value!r}")


def _pairs_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field {key!r}")
        result[key] = value
    return result


def _strict_json(value: str | bytes | bytearray) -> Mapping[str, Any]:
    if isinstance(value, (bytes, bytearray)):
        try:
            value = bytes(value).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RouteParseError("routing response is not valid UTF-8") from exc
    if not isinstance(value, str):
        raise RouteParseError("routing response must contain a JSON string")
    value = value.strip()
    if not value:
        raise RouteParseError("routing response is empty")

    # Gemma (and a number of llama.cpp-compatible chat templates) may wrap a
    # single JSON document in a Markdown ``json`` fence.  Keep this one
    # compatibility exception deliberately narrow: the fence must be the
    # complete response, have no prose before/after it, and contain exactly
    # one closing marker.  Plain JSON remains strict below.
    if value.startswith("```json"):
        match = re.fullmatch(
            r"```json[ \t]*\r?\n(?P<body>.*?)\r?\n```[ \t]*",
            value,
            flags=re.DOTALL,
        )
        if match is None:
            raise RouteParseError(
                "routing response is invalid JSON: expected one complete ```json fenced object"
            )
        body = match.group("body").strip()
        # A second fence is not an envelope we support, even if its interior
        # happens to contain another valid object.
        if re.search(r"(?m)^```", body):
            raise RouteParseError(
                "routing response is invalid JSON: multiple code fences are not allowed"
            )
        value = body
        if not value:
            raise RouteParseError("routing response is empty")
    try:
        parsed = json.loads(
            value,
            parse_constant=_reject_constant,
            object_pairs_hook=_pairs_without_duplicates,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RouteParseError(f"routing response is invalid JSON: {exc}") from exc
    if not isinstance(parsed, Mapping):
        raise RouteParseError("routing response must be a JSON object")
    return parsed


def _content_from_response(response: Any) -> Mapping[str, Any] | str | bytes:
    """Extract the one supported content envelope without permissive guessing."""

    if isinstance(response, (str, bytes, bytearray, Mapping)):
        if isinstance(response, Mapping):
            # A direct route object is the preferred fake-client shape.
            if "model" in response or "provider" in response:
                return response
            if set(response) == {"content"}:
                return _content_from_response(response["content"])
            if set(response) == {"route"}:
                return _content_from_response(response["route"])
            if set(response) == {"choices"}:
                choices = response["choices"]
                if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)) or len(choices) != 1:
                    raise RouteParseError("routing response choices must contain exactly one item")
                return _content_from_response(choices[0])
            # An OpenAI-compatible message envelope is accepted only when the
            # key set is exact; arbitrary text/answer envelopes are rejected.
            if set(response) == {"message"}:
                return _content_from_response(response["message"])
            raise RouteParseError("routing response has an unsupported object envelope")
        return response

    # SDK response objects are handled through the same exact envelope rules,
    # without importing or depending on a concrete SDK type.
    if hasattr(response, "model_dump") and callable(response.model_dump):
        try:
            return _content_from_response(response.model_dump())
        except Exception as exc:
            if isinstance(exc, RouteParseError):
                raise
            raise RouteParseError(f"could not inspect routing response: {exc}") from exc
    if hasattr(response, "dict") and callable(response.dict):
        try:
            return _content_from_response(response.dict())
        except Exception as exc:
            if isinstance(exc, RouteParseError):
                raise
            raise RouteParseError(f"could not inspect routing response: {exc}") from exc
    if hasattr(response, "choices"):
        return _content_from_response({"choices": getattr(response, "choices")})
    raise RouteParseError("routing transport returned an unsupported response type")


def _call_with_supported_kwargs(call: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call a fake/SDK method without requiring a provider-specific signature."""

    try:
        signature = inspect.signature(call)
    except (TypeError, ValueError):
        # Builtins may not expose signatures; keep the call deterministic and
        # let a TypeError become a clear transport error at the boundary.
        return call(*args, **kwargs)
    parameters = signature.parameters
    accepts_var_kwargs = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )
    if accepts_var_kwargs:
        return call(*args, **kwargs)
    filtered = {key: value for key, value in kwargs.items() if key in parameters}
    return call(*args, **filtered)


def _jsonable_catalog(value: Any) -> Any:
    """Convert a policy candidate catalog to strict JSON-compatible data."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _jsonable_catalog(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable_catalog(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _jsonable_catalog(to_dict())
    raise RouteParseError("decision policy candidate catalog is not JSON-serializable")


def _candidate_allow_lists(catalog: Any) -> tuple[list[str], list[str]]:
    """Extract ordered model/provider IDs from common catalog shapes."""

    models: list[str] = []
    providers: list[str] = []

    def add(target: list[str], value: Any) -> None:
        if isinstance(value, str) and value.strip() and value.strip() not in target:
            target.append(value.strip())
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for item in value:
                add(target, item)

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            recognised = False
            for key in ("model", "model_id"):
                if key in value:
                    add(models, value[key])
                    recognised = True
            for key in ("provider", "provider_id"):
                if key in value:
                    add(providers, value[key])
                    recognised = True
            for key in ("models", "allowed_models"):
                if key in value:
                    add(models, value[key])
                    recognised = True
            for key in ("providers", "allowed_providers"):
                if key in value:
                    add(providers, value[key])
                    recognised = True
            for key in ("candidates", "routes", "entries"):
                if key in value:
                    visit(value[key])
                    recognised = True
            if not recognised:
                for item in value.values():
                    if isinstance(item, (Mapping, list, tuple)):
                        visit(item)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for item in value:
                visit(item)

    visit(catalog)
    return models, providers


class GemmaRouterProvider(Router):
    """Route through an injected Gemma model using a strict JSON contract."""

    def __init__(
        self,
        client: RoutingModelClient | Callable[..., Any] | Any,
        model: str | None = None,
        *,
        model_name: str | None = None,
        routing_model: str | None = None,
        provider: str | None = None,
        provider_name: str | None = None,
        routing_provider: str | None = None,
        allowed_models: Sequence[str] | None = None,
        allowed_providers: Sequence[str] | None = None,
        temperature: float = 0.0,
        system_prompt: str = SYSTEM_PROMPT,
        decision_policy: Any = None,
    ) -> None:
        if client is None or not (callable(client) or hasattr(client, "chat") or hasattr(client, "complete")):
            raise TypeError("client must provide chat/complete or be callable")
        names = [item for item in (model, model_name, routing_model) if item is not None]
        if not names or any(not isinstance(item, str) or not item.strip() for item in names):
            raise ValueError("a configured Gemma routing model name is required")
        if any(item.strip() != names[0].strip() for item in names[1:]):
            raise ValueError("model, model_name, and routing_model disagree")
        self.model = names[0].strip()
        self.model_name = self.model
        self.routing_model = self.model

        providers = [item for item in (provider, provider_name, routing_provider) if item is not None]
        if any(not isinstance(item, str) or not item.strip() for item in providers):
            raise ValueError("routing provider name must be a non-empty string")
        if any(item.strip() != providers[0].strip() for item in providers[1:]):
            raise ValueError("provider, provider_name, and routing_provider disagree")
        self.provider = providers[0].strip() if providers else None
        self.provider_name = self.provider
        self.routing_provider = self.provider

        self.allowed_models = self._names(allowed_models, "allowed_models")
        self.allowed_providers = self._names(allowed_providers, "allowed_providers")
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
            raise ValueError("temperature must be a finite number")
        self.temperature = float(temperature)
        if not math.isfinite(self.temperature):
            raise ValueError("temperature must be a finite number")
        if not isinstance(system_prompt, str) or not system_prompt.strip():
            raise ValueError("system_prompt must be a non-empty string")
        self.system_prompt = system_prompt.strip()
        self.client = client
        self.decision_policy = decision_policy

    @staticmethod
    def _names(values: Sequence[str] | None, label: str) -> tuple[str, ...] | None:
        if values is None:
            return None
        if isinstance(values, (str, bytes)):
            raise ValueError(f"{label} must be a sequence of names")
        result: list[str] = []
        for index, value in enumerate(values):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label}[{index}] must be a non-empty string")
            value = value.strip()
            if value not in result:
                result.append(value)
        return tuple(result)

    def request_payload(self, request: RouterRequest) -> dict[str, Any]:
        request = coerce_request(request)
        payload: dict[str, Any] = {
            "request": request.to_dict(),
            "response_schema": ROUTE_DECISION_SCHEMA,
            "allowed_models": list(self.allowed_models) if self.allowed_models is not None else None,
            "allowed_providers": list(self.allowed_providers) if self.allowed_providers is not None else None,
        }
        if self.decision_policy is not None:
            prompt_candidates = getattr(self.decision_policy, "prompt_candidates", None)
            if not callable(prompt_candidates):
                raise RouteParseError("decision_policy must provide prompt_candidates(request)")
            try:
                catalog = _jsonable_catalog(prompt_candidates(request))
            except RouteParseError:
                raise
            except Exception as exc:
                raise RouteParseError(f"decision policy candidate lookup failed: {exc}") from exc
            models, providers = _candidate_allow_lists(catalog)
            payload["candidate_catalog"] = catalog
            # A policy owns the per-request candidate set.  Empty lists are
            # intentional: they fail closed instead of falling back to stale
            # static allow-lists.
            payload["allowed_models"] = models
            payload["allowed_providers"] = providers
        return payload

    def _system_prompt_for_payload(self, payload: Mapping[str, Any]) -> str:
        """Add explicit allow-list rules when this request supplies them."""

        constraints: list[str] = []
        allowed_models = payload.get("allowed_models")
        if allowed_models is not None:
            constraints.append(
                "The `model` field MUST be selected only from the exact "
                f"`allowed_models` list: {json.dumps(allowed_models, ensure_ascii=False)}."
            )
        allowed_providers = payload.get("allowed_providers")
        if allowed_providers is not None:
            constraints.append(
                "The `provider` field MUST be selected only from the exact "
                f"`allowed_providers` list: {json.dumps(allowed_providers, ensure_ascii=False)}."
            )
        if not constraints:
            return self.system_prompt
        return f"{self.system_prompt}\n\n" + "\n".join(constraints)

    def build_messages(self, request: RouterRequest) -> list[dict[str, str]]:
        payload = self.request_payload(request)
        return self._build_messages_from_payload(payload)

    def _build_messages_from_payload(self, payload: Mapping[str, Any]) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self._system_prompt_for_payload(payload)},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
            },
        ]

    def _invoke_client(self, messages: list[dict[str, str]]) -> Any:
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            # OpenAI-compatible clients understand this hint; the signature
            # filter keeps legacy ``chat(model, message, temperature)`` fakes
            # usable without a second side-effecting call.
            "response_format": {"type": "json_object"},
        }
        try:
            if hasattr(self.client, "complete"):
                return _call_with_supported_kwargs(self.client.complete, **kwargs)
            if hasattr(self.client, "chat"):
                # The legacy ``chat(model, prompt, ...)`` port has no separate
                # system-message slot.  Fold the system instruction into one
                # clearly delimited classification prompt so it cannot be
                # silently dropped (the previous implementation sent only the
                # request JSON and allowed Gemma to answer the user directly).
                prompt = (
                    "SYSTEM INSTRUCTIONS:\n"
                    f"{messages[0]['content']}\n\n"
                    "ROUTING REQUEST (JSON):\n"
                    f"{messages[-1]['content']}\n\n"
                    "OUTPUT REQUIREMENT: Return exactly one JSON route-decision "
                    "object and no other text."
                )
                return _call_with_supported_kwargs(
                    self.client.chat,
                    self.model,
                    prompt,
                    temperature=self.temperature,
                    response_format=kwargs["response_format"],
                )
            return _call_with_supported_kwargs(self.client, **kwargs)
        except Exception as exc:
            # Do not let transport/SDK exception classes cross the router port.
            raise RouterTransportError(f"routing model invocation failed: {exc}") from exc

    def _parse_response(
        self,
        response: Any,
        *,
        allowed_models: Sequence[str] | None,
        allowed_providers: Sequence[str] | None,
    ) -> RouteDecision:
        content = _content_from_response(response)
        if isinstance(content, Mapping):
            document = content
        else:
            document = _strict_json(content)
        try:
            decision = RouteDecision.from_mapping(document)
        except RouteParseError:
            raise
        except Exception as exc:
            raise RouteParseError(f"invalid route decision: {exc}") from exc
        if allowed_models is not None and decision.model not in allowed_models:
            raise RouteParseError(f"route model {decision.model!r} is not configured")
        if allowed_providers is not None and decision.provider not in allowed_providers:
            raise RouteParseError(f"route provider {decision.provider!r} is not configured")
        return decision

    def parse_response(self, response: Any) -> RouteDecision:
        """Parse using the adapter's static allow-lists (legacy behavior)."""

        return self._parse_response(
            response,
            allowed_models=self.allowed_models,
            allowed_providers=self.allowed_providers,
        )

    def route(self, request: RouterRequest) -> RouteDecision:
        request = coerce_request(request)
        payload = self.request_payload(request)
        response = self._invoke_client(self._build_messages_from_payload(payload))
        decision = self._parse_response(
            response,
            allowed_models=payload.get("allowed_models"),
            allowed_providers=payload.get("allowed_providers"),
        )
        if self.decision_policy is not None:
            validate = getattr(self.decision_policy, "validate", None)
            if not callable(validate):
                raise RouteParseError("decision_policy must provide validate(request, decision)")
            try:
                accepted = validate(request, decision)
            except RouteParseError:
                raise
            except Exception as exc:
                raise RouteParseError(f"decision policy validation failed: {exc}") from exc
            if accepted is False:
                raise RouteParseError("decision policy rejected route decision")
        return decision

    # Friendly aliases for integrations that call the adapter explicitly.
    decide = route
    select = route


GemmaRouterAdapter = GemmaRouterProvider
GemmaRouter = GemmaRouterProvider


__all__ = [
    "GemmaRouter",
    "GemmaRouterAdapter",
    "GemmaRouterProvider",
    "ROUTE_DECISION_SCHEMA",
    "RoutingModelClient",
]
