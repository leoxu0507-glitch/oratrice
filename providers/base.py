# -*- coding: utf-8 -*-
"""Provider contracts shared by concrete adapters.

The provider package is deliberately independent from the core/router layers.
The types in this module are small, serialisable values; they do not perform
network or model work.  Adapters may accept the legacy ``chat(model, message)``
shape, but the canonical interface uses :class:`ChatRequest` and returns
normalised response/chunk values.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import base64
import binascii
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlsplit


class ContentPart:
    """Base class for provider-neutral structured message content.

    Only text and image parts are intentionally supported by this contract.
    Concrete parts never read local files: image sources must be an ``http`` or
    ``https`` URL, or an ``image/*`` base64 data URL.  A bare path and
    ``file://`` reference are rejected explicitly so adapters cannot
    accidentally exfiltrate a local file.
    """

    __slots__ = ()

    @property
    def type(self) -> str:  # pragma: no cover - implemented by subclasses
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        """Serialise this part using OpenAI-compatible content-part shape."""

        raise NotImplementedError

    to_openai = to_dict
    to_openai_dict = to_dict
    to_payload = to_dict


def _validate_text_content(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("text content must be a string")
    # NUL is not valid text for the HTTP JSON contract and is usually a sign
    # that bytes/local-file content was passed accidentally.
    if "\x00" in value:
        raise ValueError("text content contains an invalid character")
    return value


def _validate_image_url(value: Any) -> str:
    """Validate an image URL without ever echoing it in an exception."""

    if not isinstance(value, str):
        raise TypeError("image URL must be a string")
    if not value or any(char in value for char in "\r\n\x00"):
        raise ValueError("image URL is invalid")

    lowered = value.lower()
    if lowered.startswith(("http://", "https://")):
        try:
            parsed = urlsplit(value)
        except ValueError as exc:
            raise ValueError("image URL is invalid") from None
        if not parsed.netloc:
            raise ValueError("image URL is invalid")
        return value

    if lowered.startswith("data:"):
        header, separator, payload = value.partition(",")
        if not separator or not payload:
            raise ValueError("image data URL is invalid")
        media = header[5:].split(";", 1)[0].lower()
        if not media.startswith("image/"):
            raise ValueError("image data URL must use an image MIME type")
        parameters = header[5:].split(";")[1:]
        if "base64" not in {item.lower() for item in parameters}:
            raise ValueError("image data URL must be base64 encoded")
        try:
            base64.b64decode(payload, validate=True)
        except (ValueError, TypeError, binascii.Error):
            raise ValueError("image data URL is invalid") from None
        return value

    # Local paths and arbitrary URI schemes are intentionally unsupported.
    raise ValueError("local image references are unsupported; use an https URL or image data URL")


@dataclass(frozen=True, slots=True, init=False, repr=False)
class TextPart(ContentPart):
    """A text content part in a multimodal user message."""

    text: str

    def __init__(self, text: Any = None, *, value: Any = None) -> None:
        if text is None:
            text = value
        elif value is not None and text != value:
            raise TypeError("text and value disagree")
        if text is None:
            raise TypeError("text content is required")
        object.__setattr__(self, "text", _validate_text_content(text))

    @property
    def type(self) -> str:
        return "text"

    def to_dict(self) -> dict[str, Any]:
        return {"type": "text", "text": self.text}

    to_payload = to_dict

    def __repr__(self) -> str:
        # Prompt text is intentionally omitted from diagnostic representations.
        return "TextPart(text=<redacted>)"


@dataclass(frozen=True, slots=True, init=False, repr=False)
class ImagePart(ContentPart):
    """An OpenAI-compatible image URL/data-URL content part.

    ``detail`` is optional and accepts the OpenAI values ``auto``, ``low`` or
    ``high``.  No local path is read or encoded by this class.
    """

    url: str
    detail: str | None

    def __init__(
        self,
        url: Any = None,
        *,
        image_url: Any = None,
        source: Any = None,
        local_path: Any = None,
        detail: Any = None,
    ) -> None:
        supplied = [item for item in (url, image_url, source, local_path) if item is not None]
        if len(supplied) != 1:
            if local_path is not None:
                raise ValueError("local image references are unsupported; use an https URL or image data URL")
            raise TypeError("provide exactly one image URL")
        candidate = supplied[0]
        if local_path is not None:
            raise ValueError("local image references are unsupported; use an https URL or image data URL")
        if isinstance(candidate, Mapping):
            unknown = set(candidate) - {"url", "detail"}
            if unknown:
                raise ValueError("image URL object contains unsupported fields")
            detail = candidate.get("detail", detail)
            candidate = candidate.get("url")
        object.__setattr__(self, "url", _validate_image_url(candidate))
        if detail is not None:
            if not isinstance(detail, str) or detail.lower() not in {"auto", "low", "high"}:
                raise ValueError("image detail must be auto, low, or high")
            detail = detail.lower()
        object.__setattr__(self, "detail", detail)

    @property
    def type(self) -> str:
        return "image_url"

    @property
    def image_url(self) -> str:
        return self.url

    def to_dict(self) -> dict[str, Any]:
        image_url: dict[str, Any] = {"url": self.url}
        if self.detail is not None:
            image_url["detail"] = self.detail
        return {"type": "image_url", "image_url": image_url}

    to_payload = to_dict

    def __repr__(self) -> str:
        # Image URLs (including base64 payloads) are never included in reprs.
        return "ImagePart(url=<redacted>)"


# Descriptive aliases used by integrations and tests that mirror OpenAI names.
TextContentPart = TextPart
ImageContentPart = ImagePart
TextContent = TextPart
ImageContent = ImagePart
MessageContentPart = ContentPart


def _coerce_content_part(value: Any) -> ContentPart:
    if isinstance(value, ContentPart):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("content parts must be text/image objects")
    part_type = value.get("type")
    if part_type in {"text", "input_text", "output_text"}:
        unknown = set(value) - {"type", "text"}
        if unknown:
            raise ValueError("text content part contains unsupported fields")
        return TextPart(value.get("text"))
    if part_type in {"image_url", "image", "input_image"}:
        unknown = set(value) - {"type", "image_url", "url", "detail"}
        if unknown:
            raise ValueError("image content part contains unsupported fields")
        image_url = value.get("image_url", value.get("url"))
        detail = value.get("detail")
        if isinstance(image_url, Mapping):
            return ImagePart(image_url, detail=detail)
        return ImagePart(image_url, detail=detail)
    raise ValueError("content part type must be text or image_url")


def normalize_content(value: Any) -> str | tuple[ContentPart, ...]:
    """Validate and freeze a message's text or structured content.

    Strings stay strings for complete backwards compatibility.  Structured
    content is stored as a tuple and serialised only at the provider boundary.
    """

    if isinstance(value, str):
        return _validate_text_content(value)
    if isinstance(value, ContentPart):
        return (value,)
    if isinstance(value, (list, tuple)):
        if not value:
            raise ValueError("structured message content must contain at least one part")
        return tuple(_coerce_content_part(item) for item in value)
    raise TypeError("message content must be text or a sequence of text/image parts")


def content_to_text(value: Any) -> str:
    """Return only text for routing/legacy adapters, never image source data."""

    if isinstance(value, str):
        return value
    if isinstance(value, ContentPart):
        return value.text if isinstance(value, TextPart) else ""
    if isinstance(value, (list, tuple)):
        return "".join(content_to_text(item) for item in value)
    raise TypeError("message content must be text or structured parts")


def content_has_image(value: Any) -> bool:
    if isinstance(value, ImagePart):
        return True
    if isinstance(value, (list, tuple)):
        return any(content_has_image(item) for item in value)
    return False


def _as_message(value: Any) -> "ChatMessage":
    """Coerce a common OpenAI-style message value into ``ChatMessage``."""

    if isinstance(value, ChatMessage):
        return value
    if isinstance(value, Mapping):
        role = value.get("role", "user")
        content = value.get("content", "")
        metadata = value.get("metadata", {})
        return ChatMessage(
            role=role,
            content=content,
            name=value.get("name"),
            metadata=metadata,
        )
    if isinstance(value, str):
        return ChatMessage(role="user", content=value)
    if isinstance(value, (tuple, list)) and len(value) == 2:
        return ChatMessage(role=value[0], content=value[1])
    raise TypeError("messages must contain ChatMessage or role/content mappings")


@dataclass(frozen=True, slots=True, repr=False)
class ChatMessage:
    """A provider-neutral chat message."""

    role: str
    content: str | tuple[ContentPart, ...]
    name: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.role, str) or not self.role.strip():
            raise ValueError("message role must be a non-empty string")
        object.__setattr__(self, "content", normalize_content(self.content))
        if not isinstance(self.metadata, Mapping):
            raise TypeError("message metadata must be a mapping")

    @property
    def content_parts(self) -> tuple[ContentPart, ...] | None:
        """Structured parts, or ``None`` for a legacy plain string."""

        return self.content if isinstance(self.content, tuple) else None

    @property
    def multimodal(self) -> bool:
        return isinstance(self.content, tuple)

    def __repr__(self) -> str:
        # Never expose prompt/image data if a message is included in a log.
        kind = "structured" if isinstance(self.content, tuple) else "text"
        return f"ChatMessage(role={self.role!r}, content=<{kind} redacted>)"

    def to_dict(self) -> dict[str, Any]:
        content: Any = self.content
        if isinstance(content, tuple):
            content = [part.to_dict() for part in content]
        result: dict[str, Any] = {"role": self.role, "content": content}
        if self.name is not None:
            result["name"] = self.name
        if self.metadata:
            result["metadata"] = dict(self.metadata)
        return result

    to_openai = to_dict
    to_payload = to_dict


@dataclass(frozen=True, slots=True, init=False)
class ChatRequest:
    """Canonical non-streaming/streaming request.

    ``message="..."`` and a string ``messages`` argument are accepted as
    convenience/compatibility forms.  ``messages`` is stored as a tuple so a
    request can safely cross provider boundaries without mutation.
    """

    model: str
    messages: tuple[ChatMessage, ...]
    temperature: float | None
    max_tokens: int | None
    top_p: float | None
    stop: str | tuple[str, ...] | None
    stream: bool
    timeout: float | None
    metadata: Mapping[str, Any]
    options: Mapping[str, Any]

    def __init__(
        self,
        model: str,
        messages: Iterable[Any] | Any | None = None,
        *,
        message: Any = None,
        temperature: float | None = 0.7,
        max_tokens: int | None = None,
        top_p: float | None = None,
        stop: str | Iterable[str] | None = None,
        stream: bool = False,
        timeout: float | None = None,
        metadata: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
        **extra: Any,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a non-empty string")
        if messages is not None and message is not None:
            raise TypeError("provide either messages or message, not both")
        if message is not None:
            values = (ChatMessage(role="user", content=message),)
        elif messages is None:
            values = ()
        elif isinstance(messages, (str, ChatMessage, Mapping)):
            values = (_as_message(messages),)
        else:
            values = tuple(_as_message(item) for item in messages)
        if not values:
            raise ValueError("at least one chat message is required")
        if stop is not None and not isinstance(stop, str):
            stop = tuple(str(item) for item in stop)
        merged_options = dict(options or {})
        merged_options.update(extra)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "messages", values)
        object.__setattr__(self, "temperature", temperature)
        object.__setattr__(self, "max_tokens", max_tokens)
        object.__setattr__(self, "top_p", top_p)
        object.__setattr__(self, "stop", stop)
        object.__setattr__(self, "stream", bool(stream))
        object.__setattr__(self, "timeout", timeout)
        object.__setattr__(self, "metadata", dict(metadata or {}))
        object.__setattr__(self, "options", merged_options)

    @property
    def message(self) -> str:
        """Return text-only content for legacy adapters and routing.

        Canonical adapters use :meth:`to_payload` and retain image parts.  The
        legacy string property deliberately omits image source data.
        """

        return content_to_text(self.messages[0].content) if len(self.messages) == 1 else "\n".join(
            content_to_text(item.content) for item in self.messages
        )

    @property
    def text(self) -> str:
        return self.message

    @property
    def multimodal(self) -> bool:
        return any(item.multimodal for item in self.messages)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "model": self.model,
            "messages": [item.to_dict() for item in self.messages],
            "stream": self.stream,
        }
        for key in ("temperature", "max_tokens", "top_p", "stop"):
            value = getattr(self, key)
            if value is not None:
                result[key] = list(value) if key == "stop" and isinstance(value, tuple) else value
        result.update(self.options)
        return result

    # OpenAI-compatible adapters conventionally call this a payload.
    to_payload = to_dict


@dataclass(frozen=True, slots=True, init=False)
class ChatResponse:
    """Normalised completion response."""

    content: str
    model: str | None
    finish_reason: str | None
    usage: Mapping[str, Any]
    provider: str | None
    request_id: str | None
    raw: Any
    metadata: Mapping[str, Any]

    def __init__(
        self,
        content: str | None = None,
        *,
        text: str | None = None,
        model: str | None = None,
        finish_reason: str | None = None,
        usage: Mapping[str, Any] | None = None,
        provider: str | None = None,
        request_id: str | None = None,
        raw: Any = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if content is None:
            content = text
        if content is None:
            content = ""
        if not isinstance(content, str):
            raise TypeError("response content must be a string")
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "finish_reason", finish_reason)
        object.__setattr__(self, "usage", dict(usage or {}))
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "raw", raw)
        object.__setattr__(self, "metadata", dict(metadata or {}))

    @property
    def text(self) -> str:
        return self.content

    @property
    def message(self) -> ChatMessage:
        return ChatMessage(role="assistant", content=self.content)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"content": self.content}
        for key in ("model", "finish_reason", "provider", "request_id"):
            value = getattr(self, key)
            if value is not None:
                result[key] = value
        if self.usage:
            result["usage"] = dict(self.usage)
        if self.metadata:
            result["metadata"] = dict(self.metadata)
        return result


@dataclass(frozen=True, slots=True, init=False)
class ChatChunk:
    """A normalised item yielded by a streaming completion."""

    content: str
    model: str | None
    index: int | None
    finish_reason: str | None
    provider: str | None
    request_id: str | None
    usage: Mapping[str, Any]
    raw: Any

    def __init__(
        self,
        content: str | None = None,
        *,
        text: str | None = None,
        delta: str | None = None,
        model: str | None = None,
        index: int | None = None,
        finish_reason: str | None = None,
        provider: str | None = None,
        request_id: str | None = None,
        usage: Mapping[str, Any] | None = None,
        raw: Any = None,
    ) -> None:
        if content is None:
            content = text if text is not None else delta
        if content is None:
            content = ""
        if not isinstance(content, str):
            raise TypeError("chunk content must be a string")
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "index", index)
        object.__setattr__(self, "finish_reason", finish_reason)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "usage", dict(usage or {}))
        object.__setattr__(self, "raw", raw)

    @property
    def text(self) -> str:
        return self.content

    @property
    def delta(self) -> str:
        return self.content

    @property
    def done(self) -> bool:
        return self.finish_reason is not None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"content": self.content}
        for key in ("model", "index", "finish_reason", "provider", "request_id"):
            value = getattr(self, key)
            if value is not None:
                result[key] = value
        if self.usage:
            result["usage"] = dict(self.usage)
        return result


@dataclass(frozen=True, slots=True, init=False)
class ProviderCapabilities:
    """Advertised operations of a provider adapter."""

    supports_chat: bool
    supports_stream: bool
    supports_models: bool
    supports_health: bool
    supports_vision: bool
    max_context_tokens: int | None
    metadata: Mapping[str, Any]

    def __init__(
        self,
        supports_chat: bool = True,
        supports_stream: bool = True,
        supports_models: bool = True,
        supports_health: bool = True,
        max_context_tokens: int | None = None,
        metadata: Mapping[str, Any] | None = None,
        supports_vision: bool = False,
        **aliases: Any,
    ) -> None:
        if "chat" in aliases:
            supports_chat = aliases.pop("chat")
        if "stream" in aliases:
            supports_stream = aliases.pop("stream")
        if "streaming" in aliases:
            supports_stream = aliases.pop("streaming")
        if "models" in aliases:
            supports_models = aliases.pop("models")
        if "health" in aliases:
            supports_health = aliases.pop("health")
        if "vision" in aliases:
            supports_vision = aliases.pop("vision")
        if "multimodal" in aliases:
            supports_vision = aliases.pop("multimodal")
        if aliases:
            raise TypeError(f"unknown capability fields: {', '.join(sorted(aliases))}")
        object.__setattr__(self, "supports_chat", bool(supports_chat))
        object.__setattr__(self, "supports_stream", bool(supports_stream))
        object.__setattr__(self, "supports_models", bool(supports_models))
        object.__setattr__(self, "supports_health", bool(supports_health))
        object.__setattr__(self, "supports_vision", bool(supports_vision))
        object.__setattr__(self, "max_context_tokens", max_context_tokens)
        object.__setattr__(self, "metadata", dict(metadata or {}))

    @property
    def chat(self) -> bool:
        return self.supports_chat

    @property
    def stream(self) -> bool:
        return self.supports_stream

    @property
    def streaming(self) -> bool:
        return self.supports_stream

    @property
    def models(self) -> bool:
        return self.supports_models

    @property
    def health(self) -> bool:
        return self.supports_health

    @property
    def vision(self) -> bool:
        return self.supports_vision

    @property
    def multimodal(self) -> bool:
        return self.supports_vision

    def to_dict(self) -> dict[str, Any]:
        result = {
            "chat": self.supports_chat,
            "stream": self.supports_stream,
            "models": self.supports_models,
            "health": self.supports_health,
        }
        if self.supports_vision:
            result["vision"] = True
        if self.max_context_tokens is not None:
            result["max_context_tokens"] = self.max_context_tokens
        if self.metadata:
            result["metadata"] = dict(self.metadata)
        return result


@dataclass(frozen=True, slots=True, init=False)
class ProviderHealth(Mapping[str, Any]):
    """Normalised health result, retaining mapping-style legacy access."""

    status: str
    latency_ms: float | None
    message: str | None
    details: Mapping[str, Any]
    provider: str | None
    checked_at: datetime | None

    def __init__(
        self,
        status: str = "unknown",
        *,
        healthy: bool | None = None,
        ok: bool | None = None,
        latency_ms: float | None = None,
        message: str | None = None,
        details: Mapping[str, Any] | None = None,
        provider: str | None = None,
        checked_at: datetime | None = None,
        **extra: Any,
    ) -> None:
        if healthy is None and ok is not None:
            healthy = ok
        if healthy is not None:
            status = "healthy" if healthy else "unhealthy"
        if not isinstance(status, str) or not status:
            status = "unknown"
        merged_details = dict(details or {})
        merged_details.update(extra)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "latency_ms", latency_ms)
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "details", merged_details)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(
            self,
            "checked_at",
            checked_at or datetime.now(timezone.utc),
        )

    @property
    def healthy(self) -> bool:
        return self.status.lower() in {"ok", "healthy", "ready", "up"}

    @property
    def ok(self) -> bool:
        return self.healthy

    @property
    def is_healthy(self) -> bool:
        return self.healthy

    @property
    def timestamp(self) -> datetime | None:
        return self.checked_at

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status,
            "healthy": self.healthy,
        }
        if self.latency_ms is not None:
            result["latency_ms"] = self.latency_ms
        if self.message is not None:
            result["message"] = self.message
        if self.provider is not None:
            result["provider"] = self.provider
        if self.checked_at is not None:
            result["checked_at"] = self.checked_at.isoformat()
        result.update(self.details)
        return result

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __iter__(self):
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, ProviderHealth):
            return self.to_dict() == other.to_dict()
        if isinstance(other, Mapping):
            expected = dict(other)
            return all(self.to_dict().get(key) == value for key, value in expected.items())
        return NotImplemented


class ProviderError(RuntimeError):
    """Stable provider-facing error model.

    Adapters should wrap transport/SDK exceptions in this type (or a
    specialised subclass) so provider-specific exceptions never cross the
    core boundary.
    """

    code = "provider_error"

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        code: str | None = None,
        retryable: bool = False,
        status_code: int | None = None,
        cause: BaseException | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = str(message)
        self.provider = provider
        self.code = code or type(self).code
        self.retryable = bool(retryable)
        self.status_code = status_code
        self.cause = cause
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.provider is not None:
            result["provider"] = self.provider
        if self.status_code is not None:
            result["status_code"] = self.status_code
        if self.details:
            result["details"] = dict(self.details)
        return result


class ProviderConfigurationError(ProviderError):
    code = "configuration_error"


class ProviderRequestError(ProviderError):
    code = "request_error"


class ProviderResponseError(ProviderError):
    code = "response_error"


class ProviderTimeoutError(ProviderRequestError):
    code = "timeout"

    def __init__(self, message: str = "provider request timed out", **kwargs: Any) -> None:
        kwargs.setdefault("retryable", True)
        super().__init__(message, **kwargs)


class ProviderUnavailableError(ProviderError):
    code = "unavailable"

    def __init__(self, message: str = "provider is unavailable", **kwargs: Any) -> None:
        kwargs.setdefault("retryable", True)
        super().__init__(message, **kwargs)


class ProviderCapabilityError(ProviderError):
    code = "unsupported_capability"


# Descriptive alias used by some callers.
ProviderTransportError = ProviderRequestError


@runtime_checkable
class ProviderProtocol(Protocol):
    """Structural provider port used by registries/managers and test fakes."""

    provider_id: str

    def chat(self, request: ChatRequest) -> ChatResponse: ...

    def stream(self, request: ChatRequest) -> Iterator[ChatChunk]: ...

    def health(self) -> ProviderHealth: ...

    def models(self) -> Any: ...

    def capabilities(self) -> ProviderCapabilities: ...


ProviderPort = ProviderProtocol

# A few integrations use ``Provider`` as the public protocol name.  Keep it as
# an alias rather than introducing a second implementation.
Provider = ProviderProtocol

# Descriptive aliases for callers that prefer completion-oriented names.
ChatCompletionRequest = ChatRequest
ChatCompletionResponse = ChatResponse
StreamChunk = ChatChunk


class BaseProvider(ABC):
    """Compatibility base class for concrete provider adapters."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        provider_id: str | None = None,
        api_key: str | None = None,
        timeout: float = 120.0,
        **_: Any,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.provider_id = provider_id or type(self).__name__
        self.api_key = api_key
        self.timeout = timeout

    @abstractmethod
    def health(self) -> ProviderHealth | Mapping[str, Any]:
        """Return provider health without exposing transport exceptions."""

    @abstractmethod
    def models(self) -> Any:
        """Return provider model metadata."""

    @abstractmethod
    def chat(self, request: ChatRequest | str, message: str | None = None, **kwargs: Any) -> ChatResponse | str:
        """Perform a chat request (legacy model/message is accepted)."""

    @abstractmethod
    def stream(self, request: ChatRequest | str, message: str | None = None, **kwargs: Any) -> Iterator[ChatChunk | str]:
        """Stream chat chunks (legacy model/message is accepted)."""

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()

    # Compatibility spelling used by provider-manager implementations.
    def get_capabilities(self) -> ProviderCapabilities:
        return self.capabilities()

    def health_status(self) -> ProviderHealth:
        value = self.health()
        if isinstance(value, ProviderHealth):
            return value
        if isinstance(value, Mapping):
            raw = dict(value)
            status = str(raw.pop("status", "unknown"))
            healthy = raw.pop("healthy", raw.pop("ok", None))
            return ProviderHealth(
                status=status,
                healthy=healthy,
                provider=self.provider_id,
                details=raw,
            )
        return ProviderHealth(status="unknown", provider=self.provider_id)

    # Explicit name for manager implementations that prefer ``check_health``.
    check_health = health_status


def coerce_request(
    request_or_model: ChatRequest | str,
    message: str | None = None,
    *,
    temperature: float | None = 0.7,
    stream: bool = False,
    **kwargs: Any,
) -> tuple[ChatRequest, bool]:
    """Normalise canonical and legacy adapter calls.

    Returns ``(request, legacy_call)`` so adapters can preserve the historical
    string return/yield behaviour for callers that passed ``model, message``.
    """

    if isinstance(request_or_model, ChatRequest):
        return request_or_model, False
    if not isinstance(request_or_model, str):
        raise TypeError("provider request must be ChatRequest or model string")
    if message is None:
        raise TypeError("legacy provider calls require model and message")
    request = ChatRequest(
        request_or_model,
        message=message,
        temperature=temperature,
        stream=stream,
        **kwargs,
    )
    return request, True


__all__ = [
    "BaseProvider",
    "ChatChunk",
    "ChatCompletionRequest",
    "ChatCompletionResponse",
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "ContentPart",
    "ImageContent",
    "ImageContentPart",
    "ImagePart",
    "MessageContentPart",
    "Provider",
    "ProviderCapabilities",
    "ProviderCapabilityError",
    "ProviderConfigurationError",
    "ProviderError",
    "ProviderHealth",
    "ProviderPort",
    "ProviderProtocol",
    "ProviderRequestError",
    "ProviderResponseError",
    "ProviderTimeoutError",
    "ProviderTransportError",
    "ProviderUnavailableError",
    "StreamChunk",
    "TextContent",
    "TextContentPart",
    "TextPart",
    "content_has_image",
    "content_to_text",
    "coerce_request",
    "normalize_content",
]
