# -*- coding: utf-8 -*-
"""LiteLLM Gateway provider adapter.

The gateway exposes the OpenAI-compatible HTTP API that LiteLLM Proxy uses.
This module deliberately keeps the HTTP boundary small and provider-neutral:
the model string is forwarded exactly as supplied by configuration/router and
the adapter does not contain mappings for any concrete upstream vendor.

``session`` is injectable so unit tests (and callers with a shared HTTP
client) never need to make a real network call.  The adapter only consumes a
resolved ``api_key``.  Secret expansion belongs to
``core.configuration.ConfigurationLoader``; this module never reads process
environment variables and never logs request headers or payloads.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any, Iterator

try:  # ``requests`` is used by the compatibility llama adapter as well.
    import requests
except Exception:  # pragma: no cover - permits injecting a non-requests client
    requests = None  # type: ignore[assignment]

from providers.base import (
    BaseProvider,
    ChatChunk,
    ChatRequest,
    ChatResponse,
    ProviderCapabilities,
    ProviderConfigurationError,
    ProviderError,
    ProviderHealth,
    ProviderRequestError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    coerce_request,
)


def _mapping(value: Any) -> dict[str, Any]:
    """Return a shallow mapping view for config/dataclass-like values."""

    if value is None:
        return {}
    if isinstance(value, Mapping):
        result = dict(value)
    else:
        values = getattr(value, "__dict__", None)
        if not isinstance(values, Mapping):
            return {}
        result = dict(values)
    # ``ProviderConfig`` stores arbitrary adapter fields in ``options``.
    options = result.get("options")
    if isinstance(options, Mapping):
        merged = dict(options)
        merged.update({key: child for key, child in result.items() if key != "options"})
        result = merged
    return result


class LiteLLMGatewayProvider(BaseProvider):
    """Provider adapter for a LiteLLM OpenAI-compatible Gateway.

    The canonical methods accept :class:`~providers.base.ChatRequest` and
    return normalised contract values.  Historical ``chat(model, message)``
    and ``stream(model, message)`` calls remain supported and return strings,
    matching :class:`providers.llama_cpp.LlamaCppProvider`.

    Parameters can be supplied directly or through a mapping/dataclass as the
    first argument.  ``endpoint``/``gateway_url`` are aliases for ``base_url``;
    ``token``/``master_key`` are aliases for ``api_key``.  No alias implies a
    concrete upstream provider -- model selection stays configuration-driven.
    """

    def __init__(
        self,
        base_url: str | Mapping[str, Any] | Any | None = None,
        *,
        provider_id: str | None = None,
        api_key: str | None = None,
        token: str | None = None,
        master_key: str | None = None,
        endpoint: str | None = None,
        gateway_url: str | None = None,
        api_base: str | None = None,
        timeout: float = 120.0,
        session: Any = None,
        http_client: Any = None,
        model: str | None = None,
        default_model: str | None = None,
        model_map: Mapping[str, str] | None = None,
        model_aliases: Mapping[str, str] | None = None,
        models: Mapping[str, str] | None = None,
        model_mapping: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        health_path: str = "/health",
        models_path: str | None = None,
        chat_path: str | None = None,
        **kwargs: Any,
    ) -> None:
        # A ProviderConfig is often passed directly by a composition root.
        # Flatten it before applying explicit keyword overrides.
        config = _mapping(base_url) if not isinstance(base_url, str) else {}
        if config:
            base_url = config.get(
                "base_url",
                config.get("endpoint", config.get("gateway_url", config.get("api_base"))),
            )
            provider_id = provider_id or config.get("provider_id", config.get("id"))
            api_key = api_key or config.get(
                "api_key", config.get("token", config.get("master_key", config.get("secret")))
            )
            timeout = config.get("timeout", timeout)
            session = session or config.get("session", config.get("http_client"))
            model = model or config.get("model")
            default_model = default_model or config.get("default_model")
            model_map = model_map or config.get("model_map", config.get("model_aliases"))
            models = models or config.get("models")
            model_mapping = model_mapping or config.get("model_mapping")
            headers = headers or config.get("headers")
            health_path = config.get("health_path", health_path)
            models_path = models_path or config.get("models_path")
            chat_path = chat_path or config.get("chat_path")
            endpoint = endpoint or config.get("endpoint")
            gateway_url = gateway_url or config.get("gateway_url")
            api_base = api_base or config.get("api_base")
            # Preserve any provider-specific options for payload extension.
            kwargs = {key: value for key, value in config.items() if key not in {
                "base_url", "endpoint", "gateway_url", "api_base", "provider_id", "id",
                "api_key", "token", "master_key", "secret", "timeout", "session",
                "http_client", "model", "default_model", "model_map", "model_aliases", "models", "model_mapping",
                "headers", "health_path", "models_path", "chat_path", "options",
                "name", "type", "kind", "scope", "enabled",
            }} | kwargs

        resolved_url = base_url or endpoint or gateway_url or api_base
        if resolved_url is not None and not isinstance(resolved_url, str):
            raise ProviderConfigurationError(
                "LiteLLM Gateway base_url must be a string",
                provider=provider_id or "litellm_gateway",
            )
        super().__init__(
            resolved_url,
            provider_id=provider_id or "litellm_gateway",
            api_key=api_key or token or master_key,
            timeout=timeout,
            **kwargs,
        )
        self.session = session if session is not None else self._new_session()
        self.default_model = default_model or model
        self.model_map = dict(model_map or model_aliases or models or model_mapping or {})
        self._headers_extra = {str(key): str(value) for key, value in (headers or {}).items()}
        self.health_path = self._normalise_path(health_path or "/health")
        self.models_path = self._normalise_path(models_path or "/models")
        self.chat_path = self._normalise_path(chat_path or "/chat/completions")

    @staticmethod
    def _new_session() -> Any:
        if requests is None:
            raise ProviderConfigurationError(
                "LiteLLM Gateway requires an HTTP session; inject session=... when requests is unavailable",
                provider="litellm_gateway",
            )
        factory = getattr(requests, "Session", None)
        return factory() if callable(factory) else requests

    @staticmethod
    def _normalise_path(value: str) -> str:
        text = str(value).strip()
        if not text:
            return ""
        return "/" + text.strip("/")

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_chat=True,
            supports_stream=True,
            supports_models=True,
            supports_health=True,
            supports_vision=True,
            metadata={
                "driver": "litellm",
                "protocol": "openai-compatible",
                "gateway": True,
                "multimodal": True,
            },
        )

    def _require_base_url(self) -> str:
        if not self.base_url:
            raise ProviderConfigurationError(
                "LiteLLM Gateway provider requires a base_url",
                provider=self.provider_id,
            )
        return self.base_url

    def _api_base(self) -> str:
        base = self._require_base_url().rstrip("/")
        return base if base.lower().endswith("/v1") else f"{base}/v1"

    def _root_base(self) -> str:
        base = self._require_base_url().rstrip("/")
        return base[:-3] if base.lower().endswith("/v1") else base

    def _url(self, path: str, *, api: bool = True) -> str:
        root = self._api_base() if api else self._root_base()
        return f"{root}{path}"

    def _headers(self) -> dict[str, str]:
        # Never include the secret in diagnostics or object representations;
        # this dictionary is passed only to the injected HTTP client.
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        headers.update(self._headers_extra)
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @staticmethod
    def _status_code(response: Any) -> int | None:
        value = getattr(response, "status_code", None)
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _check_response(self, response: Any, *, operation: str) -> None:
        status_code = self._status_code(response)
        if status_code is not None and status_code < 400:
            return
        try:
            raise_for_status = getattr(response, "raise_for_status", None)
            if callable(raise_for_status):
                raise_for_status()
            elif status_code is None or status_code >= 400:
                raise RuntimeError("HTTP response was not successful")
        except Exception as exc:
            if isinstance(exc, ProviderError):
                raise
            retryable = status_code in {408, 409, 425, 429} or status_code is None or status_code >= 500
            if status_code is not None and status_code >= 500:
                raise ProviderUnavailableError(
                    f"LiteLLM Gateway {operation} endpoint is unavailable",
                    provider=self.provider_id,
                    status_code=status_code,
                    cause=exc,
                ) from exc
            raise ProviderResponseError(
                f"LiteLLM Gateway {operation} request returned an error",
                provider=self.provider_id,
                status_code=status_code,
                retryable=retryable,
                cause=exc,
            ) from exc

    def _json(self, response: Any, *, operation: str) -> Any:
        try:
            return response.json()
        except Exception as exc:
            raise ProviderResponseError(
                f"LiteLLM Gateway returned invalid JSON for {operation}",
                provider=self.provider_id,
                status_code=self._status_code(response),
                cause=exc,
            ) from exc

    @staticmethod
    def _request_exceptions() -> tuple[type[BaseException], ...]:
        if requests is None:
            return (TimeoutError,)
        exceptions = getattr(requests, "exceptions", None)
        result: list[type[BaseException]] = [TimeoutError]
        for name in ("Timeout", "ConnectionError", "RequestException"):
            value = getattr(exceptions, name, None)
            if isinstance(value, type) and value not in result:
                result.append(value)
        return tuple(result)

    def _send(self, method: str, url: str, *, operation: str, **kwargs: Any) -> Any:
        """Call an injected session and map transport failures to the port."""

        method_name = method.lower()
        try:
            sender = getattr(self.session, method_name, None)
            if callable(sender):
                return sender(url, **kwargs)
            sender = getattr(self.session, "request", None)
            if callable(sender):
                return sender(method.upper(), url, **kwargs)
            raise TypeError("HTTP session has no request method")
        except self._request_exceptions() as exc:
            name = type(exc).__name__.lower()
            if "timeout" in name:
                raise ProviderTimeoutError(
                    f"LiteLLM Gateway {operation} request timed out",
                    provider=self.provider_id,
                    cause=exc,
                ) from exc
            if "connection" in name:
                raise ProviderUnavailableError(
                    f"LiteLLM Gateway {operation} endpoint is unavailable",
                    provider=self.provider_id,
                    cause=exc,
                ) from exc
            raise ProviderRequestError(
                f"LiteLLM Gateway {operation} request failed",
                provider=self.provider_id,
                cause=exc,
            ) from exc
        except ProviderError:
            raise
        except Exception as exc:
            # Do not include ``str(exc)``: custom clients may embed credentials
            # in exception text.  The stable code/cause remains available to
            # callers that need diagnostics.
            raise ProviderRequestError(
                f"LiteLLM Gateway {operation} request failed",
                provider=self.provider_id,
                cause=exc,
            ) from exc

    @staticmethod
    def _extract_content(data: Mapping[str, Any]) -> tuple[str, str | None, Mapping[str, Any], str | None, str | None, int | None]:
        choices = data.get("choices") or []
        if not choices or not isinstance(choices[0], Mapping):
            content = data.get("content", data.get("output", data.get("text", "")))
            return str(content or ""), None, data.get("usage") or {}, data.get("id"), data.get("model"), None
        first = choices[0]
        message = first.get("message") or {}
        delta = first.get("delta") or {}
        content = message.get("content") if isinstance(message, Mapping) else None
        if content is None and isinstance(delta, Mapping):
            content = delta.get("content")
        if content is None:
            content = first.get("text", "")
        index = first.get("index")
        return (
            str(content or ""),
            first.get("finish_reason"),
            data.get("usage") or {},
            data.get("id"),
            data.get("model"),
            index,
        )

    def _mapped_model(self, model: str) -> str:
        if model in self.model_map:
            return str(self.model_map[model])
        return self.default_model if (not model and self.default_model) else model

    def chat(
        self,
        request_or_model: ChatRequest | str | None = None,
        message: str | None = None,
        temperature: float | None = 0.7,
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse | str:
        if request_or_model is None:
            request_or_model = model
        request, legacy = coerce_request(
            request_or_model,
            message,
            temperature=temperature,
            stream=False,
            **kwargs,
        )
        payload = request.to_payload()
        payload["model"] = self._mapped_model(request.model)
        payload["stream"] = False
        response = self._send(
            "post",
            self._url(self.chat_path),
            operation="chat",
            json=payload,
            headers=self._headers(),
            timeout=request.timeout or self.timeout,
        )
        self._check_response(response, operation="chat")
        data = self._json(response, operation="chat")
        if not isinstance(data, Mapping):
            raise ProviderResponseError(
                "LiteLLM Gateway chat response must be an object",
                provider=self.provider_id,
            )
        content, finish_reason, usage, request_id, response_model, _ = self._extract_content(data)
        result = ChatResponse(
            content=content,
            # The transport may report an upstream model path or deployment
            # identifier.  That value is provider-internal; callers need the
            # stable alias they supplied at the provider boundary.  The raw
            # response remains available on ``ChatResponse.raw`` for adapter
            # diagnostics without leaking the transport identifier into the
            # public response contract.
            model=request.model,
            finish_reason=finish_reason,
            usage=usage,
            provider=self.provider_id,
            request_id=request_id,
            raw=data,
        )
        return result.content if legacy else result

    def stream(
        self,
        request_or_model: ChatRequest | str | None = None,
        message: str | None = None,
        temperature: float | None = 0.7,
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatChunk | str]:
        if request_or_model is None:
            request_or_model = model
        request, legacy = coerce_request(
            request_or_model,
            message,
            temperature=temperature,
            stream=True,
            **kwargs,
        )
        payload = request.to_payload()
        payload["model"] = self._mapped_model(request.model)
        payload["stream"] = True
        response = self._send(
            "post",
            self._url(self.chat_path),
            operation="stream",
            json=payload,
            headers=self._headers(),
            stream=True,
            timeout=request.timeout or self.timeout,
        )
        try:
            self._check_response(response, operation="stream")
            lines = getattr(response, "iter_lines", None)
            if not callable(lines):
                raise ProviderResponseError(
                    "LiteLLM Gateway streaming response has no iter_lines()",
                    provider=self.provider_id,
                )
            for line in lines():
                if not line:
                    continue
                if isinstance(line, Mapping):
                    data = line
                else:
                    decoded = line.decode("utf-8", errors="replace") if isinstance(line, bytes) else str(line)
                    if decoded.startswith(":"):
                        continue
                    payload_str = decoded[5:].strip() if decoded.startswith("data:") else decoded.strip()
                    if payload_str == "[DONE]":
                        break
                    try:
                        data = json.loads(payload_str)
                    except (TypeError, json.JSONDecodeError):
                        continue
                if not isinstance(data, Mapping):
                    continue
                content, finish_reason, usage, request_id, response_model, index = self._extract_content(data)
                if content or finish_reason is not None:
                    chunk = ChatChunk(
                        content=content,
                        # Keep streamed chunks aligned with non-streaming
                        # responses: expose the requested alias, not a
                        # transport-specific upstream model identifier.
                        model=request.model,
                        index=index,
                        finish_reason=finish_reason,
                        provider=self.provider_id,
                        request_id=request_id,
                        usage=usage,
                        raw=data,
                    )
                    yield chunk.content if legacy else chunk
        except ProviderError:
            raise
        except self._request_exceptions() as exc:
            name = type(exc).__name__.lower()
            if "timeout" in name:
                raise ProviderTimeoutError(
                    "LiteLLM Gateway stream timed out",
                    provider=self.provider_id,
                    cause=exc,
                ) from exc
            raise ProviderRequestError(
                "LiteLLM Gateway stream failed",
                provider=self.provider_id,
                cause=exc,
            ) from exc
        except Exception as exc:
            raise ProviderRequestError(
                "LiteLLM Gateway stream failed",
                provider=self.provider_id,
                cause=exc,
            ) from exc
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

    def health(self) -> ProviderHealth:
        started = time.perf_counter()
        try:
            response = self._send(
                "get",
                self._url(self.health_path, api=False),
                operation="health",
                headers=self._headers(),
                timeout=min(float(self.timeout), 5.0),
            )
            self._check_response(response, operation="health")
            try:
                payload = self._json(response, operation="health")
            except ProviderResponseError:
                # A health endpoint may intentionally return an empty body;
                # successful HTTP status is still useful health information.
                payload = {}
            details = dict(payload) if isinstance(payload, Mapping) else ({"response": payload} if payload else {})
            status = str(details.pop("status", details.pop("health", "healthy")))
            return ProviderHealth(
                status=status,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                provider=self.provider_id,
                details=details,
            )
        except ProviderError as exc:
            # Health is diagnostic and returns an unhealthy value rather than
            # leaking transport exceptions through a status probe.
            return ProviderHealth(
                status="unhealthy",
                message=exc.message,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                provider=self.provider_id,
                details={"code": exc.code, **exc.details},
            )

    def models(self) -> Any:
        response = self._send(
            "get",
            self._url(self.models_path),
            operation="models",
            headers=self._headers(),
            timeout=min(float(self.timeout), 5.0),
        )
        self._check_response(response, operation="models")
        return self._json(response, operation="models")


# Public aliases used by different composition roots while the V1 name settles.
LiteLLMProvider = LiteLLMGatewayProvider
LiteLLMGateway = LiteLLMGatewayProvider

__all__ = ["LiteLLMGateway", "LiteLLMGatewayProvider", "LiteLLMProvider"]
