# -*- coding: utf-8 -*-
"""Direct llama.cpp (OpenAI-compatible HTTP) provider adapter.

The adapter intentionally depends only on ``requests`` and the provider
contracts.  It does not import LiteLLM or any core/router implementation.
Canonical calls accept :class:`~providers.base.ChatRequest` and return
``ChatResponse``/``ChatChunk`` values.  Calls using the historical
``chat(model, message)`` and ``stream(model, message)`` signatures continue to
return strings for a low-cost migration path.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any, Iterator

import requests

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


class LlamaCppProvider(BaseProvider):
    """Adapter for llama-server's OpenAI-compatible HTTP endpoints."""

    def __init__(
        self,
        base_url: str,
        *,
        provider_id: str | None = None,
        api_key: str | None = None,
        timeout: float = 120.0,
        session: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            base_url,
            provider_id=provider_id,
            api_key=api_key,
            timeout=timeout,
            **kwargs,
        )
        # ``requests`` itself is a session-like object.  A fake can be injected
        # here in tests without changing provider code or making network calls.
        self.session = session or requests

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_chat=True,
            supports_stream=True,
            supports_models=True,
            supports_health=True,
            supports_vision=True,
            metadata={
                "driver": "llama.cpp",
                "protocol": "openai-compatible",
                "multimodal": True,
            },
        )

    def _require_base_url(self) -> str:
        if not self.base_url:
            raise ProviderConfigurationError(
                "llama.cpp provider requires a base_url",
                provider=self.provider_id,
            )
        return self.base_url

    def _api_base(self) -> str:
        base = self._require_base_url()
        return base if base.lower().endswith("/v1") else f"{base}/v1"

    def _root_base(self) -> str:
        base = self._require_base_url()
        return base[:-3] if base.lower().endswith("/v1") else base

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
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
        try:
            raise_for_status = getattr(response, "raise_for_status", None)
            if callable(raise_for_status):
                raise_for_status()
            elif status_code is not None and status_code >= 400:
                raise RuntimeError(f"HTTP {status_code}")
        except Exception as exc:
            if isinstance(exc, ProviderError):
                raise
            raise ProviderResponseError(
                f"llama.cpp {operation} request failed",
                provider=self.provider_id,
                status_code=status_code,
                cause=exc,
                retryable=status_code is None or status_code >= 500,
            ) from exc

    def _json(self, response: Any, *, operation: str) -> Any:
        try:
            return response.json()
        except Exception as exc:
            raise ProviderResponseError(
                f"llama.cpp returned invalid JSON for {operation}",
                provider=self.provider_id,
                status_code=self._status_code(response),
                cause=exc,
            ) from exc

    def _request(self, method: str, url: str, *, operation: str, **kwargs: Any) -> Any:
        method_name = method.lower()
        try:
            sender = getattr(self.session, method_name)
            return sender(url, **kwargs)
        except (requests.exceptions.Timeout, TimeoutError) as exc:
            raise ProviderTimeoutError(
                f"llama.cpp {operation} request timed out",
                provider=self.provider_id,
                cause=exc,
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise ProviderUnavailableError(
                f"llama.cpp {operation} endpoint is unavailable",
                provider=self.provider_id,
                cause=exc,
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise ProviderRequestError(
                f"llama.cpp {operation} request failed",
                provider=self.provider_id,
                cause=exc,
            ) from exc
        except ProviderError:
            raise
        except Exception as exc:
            # Test doubles and alternate HTTP clients do not necessarily use
            # requests' exception classes.  Keep the public error stable.
            raise ProviderRequestError(
                f"llama.cpp {operation} request failed",
                provider=self.provider_id,
                cause=exc,
            ) from exc

    def health(self) -> ProviderHealth:
        started = time.perf_counter()
        try:
            response = self._request(
                "get",
                f"{self._root_base()}/health",
                operation="health",
                headers=self._headers(),
                timeout=min(float(self.timeout), 5.0),
            )
            self._check_response(response, operation="health")
            payload = self._json(response, operation="health")
            details = dict(payload) if isinstance(payload, Mapping) else {"response": payload}
            status = str(details.pop("status", details.pop("health", "healthy")))
            return ProviderHealth(
                status=status,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                provider=self.provider_id,
                details=details,
            )
        except ProviderError as exc:
            # Health is a diagnostic interface: an unreachable endpoint is a
            # valid unhealthy result, while chat/stream still raise errors.
            return ProviderHealth(
                status="unhealthy",
                message=exc.message,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                provider=self.provider_id,
                details={"code": exc.code, **exc.details},
            )

    def models(self) -> Any:
        response = self._request(
            "get",
            f"{self._api_base()}/models",
            operation="models",
            headers=self._headers(),
            timeout=min(float(self.timeout), 5.0),
        )
        self._check_response(response, operation="models")
        return self._json(response, operation="models")

    @staticmethod
    def _extract_content(data: Mapping[str, Any]) -> tuple[str, str | None, Mapping[str, Any], str | None, str | None]:
        choices = data.get("choices") or []
        if not choices:
            # A few llama-server versions return ``content`` directly.
            content = data.get("content", data.get("output", data.get("text", "")))
            return str(content or ""), None, data.get("usage") or {}, data.get("id"), data.get("model")
        first = choices[0] or {}
        message = first.get("message") or {}
        delta = first.get("delta") or {}
        content = message.get("content")
        if content is None:
            content = delta.get("content")
        if content is None:
            content = first.get("text", "")
        return (
            str(content or ""),
            first.get("finish_reason"),
            data.get("usage") or {},
            data.get("id"),
            data.get("model"),
        )

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
        payload["stream"] = False
        response = self._request(
            "post",
            f"{self._api_base()}/chat/completions",
            operation="chat",
            json=payload,
            headers=self._headers(),
            timeout=request.timeout or self.timeout,
        )
        self._check_response(response, operation="chat")
        data = self._json(response, operation="chat")
        if not isinstance(data, Mapping):
            raise ProviderResponseError(
                "llama.cpp chat response must be an object",
                provider=self.provider_id,
            )
        content, finish_reason, usage, request_id, response_model = self._extract_content(data)
        result = ChatResponse(
            content=content,
            # llama-server can report its resolved model path/alias in the
            # transport response.  Keep that internal value in ``raw`` and
            # expose the caller's provider-neutral request alias instead.
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
        payload["stream"] = True
        response = self._request(
            "post",
            f"{self._api_base()}/chat/completions",
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
                    "llama.cpp streaming response has no iter_lines()",
                    provider=self.provider_id,
                )
            for line in lines():
                if not line:
                    continue
                if isinstance(line, bytes):
                    decoded = line.decode("utf-8", errors="replace")
                else:
                    decoded = str(line)
                if decoded.startswith(":"):
                    continue
                if decoded.startswith("data:"):
                    payload_str = decoded[5:].strip()
                else:
                    # Some test doubles/HTTP clients return raw JSON lines.
                    payload_str = decoded.strip()
                if payload_str == "[DONE]":
                    break
                try:
                    data = json.loads(payload_str)
                except (TypeError, json.JSONDecodeError):
                    continue
                if not isinstance(data, Mapping):
                    continue
                content, finish_reason, usage, request_id, response_model = self._extract_content(data)
                choices = data.get("choices") or []
                index = choices[0].get("index") if choices and isinstance(choices[0], Mapping) else None
                if content or finish_reason is not None:
                    chunk = ChatChunk(
                        content=content,
                        # Streaming uses the same public model contract as
                        # ``chat``: return the requested alias consistently.
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
        except (requests.exceptions.Timeout, TimeoutError) as exc:
            raise ProviderTimeoutError(
                "llama.cpp stream timed out",
                provider=self.provider_id,
                cause=exc,
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise ProviderRequestError(
                "llama.cpp stream failed",
                provider=self.provider_id,
                cause=exc,
            ) from exc
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()


__all__ = ["LlamaCppProvider"]
