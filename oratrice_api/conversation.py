"""Portable bounds for client-supplied chat history."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


MAX_HISTORY_MESSAGES = 12
MAX_CONTEXT_BYTES = 1536
MESSAGE_OVERHEAD_BYTES = 32
MAX_REPLY_TOKENS = 256
MAX_CHAT_BODY_BYTES = 65536

_CONTEXT_LIMIT_MESSAGE = (
    "Conversation limit reached. Shorten your message or start a new conversation."
)


def _field(payload: Any, name: str, default: Any = None) -> Any:
    if isinstance(payload, Mapping):
        return payload.get(name, default)
    return getattr(payload, name, default)


def _content(item: Any) -> Any:
    if isinstance(item, Mapping):
        return item.get("content")
    return getattr(item, "content", None)


def _context_limit_error() -> dict[str, dict[str, str]]:
    """Return a fresh, input-free error envelope for all context limits."""

    return {
        "error": {
            "code": "context_limit",
            "message": _CONTEXT_LIMIT_MESSAGE,
        }
    }


def context_error(payload: Any) -> dict[str, dict[str, str]] | None:
    """Return a safe error envelope when supplied history exceeds its bounds.

    The byte budget counts UTF-8 content bytes plus a fixed framing allowance
    for every history message and the current message. It is deliberately a
    conservative, portable bound and is not an exact model-tokenizer estimate.
    Requests without history retain their existing sampling semantics.
    """

    history = _field(payload, "history")
    if history is None:
        return None
    if not isinstance(history, list) or len(history) > MAX_HISTORY_MESSAGES:
        return _context_limit_error()

    max_tokens = _field(payload, "max_tokens")
    if max_tokens is not None and (
        type(max_tokens) is not int or not 1 <= max_tokens <= MAX_REPLY_TOKENS
    ):
        return _context_limit_error()

    current = _field(payload, "message")
    if not isinstance(current, str) or not current.strip():
        return _context_limit_error()

    contents = [current]
    for item in history:
        value = _content(item)
        if not isinstance(value, str) or not value.strip():
            return _context_limit_error()
        contents.append(value)

    try:
        size = sum(
            len(value.encode("utf-8")) + MESSAGE_OVERHEAD_BYTES
            for value in contents
        )
    except UnicodeEncodeError:
        return _context_limit_error()

    if size > MAX_CONTEXT_BYTES:
        return _context_limit_error()
    return None


__all__ = [
    "MAX_CHAT_BODY_BYTES",
    "MAX_CONTEXT_BYTES",
    "MAX_HISTORY_MESSAGES",
    "MAX_REPLY_TOKENS",
    "MESSAGE_OVERHEAD_BYTES",
    "context_error",
]
