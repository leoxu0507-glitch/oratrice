"""Strict HTTP conversation DTO and portable context-budget checks."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from oratrice_api.contracts import ChatRequest, ConversationMessage
from oratrice_api.conversation import (
    MAX_CHAT_BODY_BYTES,
    MAX_CONTEXT_BYTES,
    MAX_HISTORY_MESSAGES,
    MAX_REPLY_TOKENS,
    MESSAGE_OVERHEAD_BYTES,
    context_error,
)


def _pair(*, user: str = "prior question", assistant: str = "prior answer"):
    return [
        {"role": "user", "content": user},
        {"role": "assistant", "content": assistant},
    ]


def test_history_dto_requires_strict_roles_content_and_known_fields():
    request = ChatRequest(message="next question", history=_pair())
    assert request.history == [
        ConversationMessage(role="user", content="prior question"),
        ConversationMessage(role="assistant", content="prior answer"),
    ]

    invalid_histories = [
        [{"role": "system", "content": "hidden instruction"}],
        [{"role": "tool", "content": "tool result"}],
        [{"role": "user", "content": 42}],
        [{"role": "user", "content": "  \t"}],
        [{"role": "user", "content": "old", "name": "extra"}],
    ]
    for history in invalid_histories:
        with pytest.raises(ValidationError):
            ChatRequest(message="next", history=history)

    with pytest.raises(ValidationError):
        ChatRequest(message="next", history=tuple(_pair()))
    with pytest.raises(ValidationError):
        ChatRequest(message="next", history=[], unexpected="field")


@pytest.mark.parametrize(
    "history",
    [
        [{"role": "user", "content": "u"}],
        _pair().__reversed__(),
        [
            {"role": "assistant", "content": "a"},
            {"role": "user", "content": "u"},
        ],
    ],
)
def test_history_requires_complete_pairs_starting_with_user(history):
    with pytest.raises(ValidationError):
        ChatRequest(message="next", history=history)


@pytest.mark.parametrize("message", ["", " \t\n", 42, ["multimodal"]])
def test_history_requires_a_nonblank_text_current_message(message):
    with pytest.raises(ValidationError):
        ChatRequest(message=message, history=[])


def test_history_budget_accepts_ascii_exact_boundary_and_rejects_one_byte_over():
    exact_message = "a" * (MAX_CONTEXT_BYTES - MESSAGE_OVERHEAD_BYTES)
    over_message = exact_message + "a"

    exact = ChatRequest(message=exact_message, history=[])
    over = ChatRequest(message=over_message, history=[])

    assert context_error(exact) is None
    assert context_error(over) == {
        "error": {
            "code": "context_limit",
            "message": "Conversation limit reached. Shorten your message or start a new conversation.",
        }
    }


def test_history_budget_counts_multibyte_history_and_current_with_framing():
    # Two one-byte history contents and their framing leave 1,438 bytes for
    # the current message, which is exactly 719 two-byte UTF-8 characters.
    history = _pair(user="u", assistant="a")
    exact = ChatRequest(message="é" * 719, history=history)
    over = ChatRequest(message="é" * 720, history=history)

    assert context_error(exact) is None
    assert context_error(over) is not None


def test_history_count_limit_is_twelve_messages():
    assert MAX_HISTORY_MESSAGES == 12
    within = [item for _ in range(MAX_HISTORY_MESSAGES // 2) for item in _pair(user="u", assistant="a")]
    over = [item for _ in range((MAX_HISTORY_MESSAGES + 2) // 2) for item in _pair(user="u", assistant="a")]

    assert context_error(ChatRequest(message="next", history=within)) is None
    assert context_error(ChatRequest(message="next", history=over)) is not None


@pytest.mark.parametrize("max_tokens", [1, MAX_REPLY_TOKENS])
def test_history_reply_token_limits_accept_valid_values(max_tokens):
    request = ChatRequest(message="next", history=[], max_tokens=max_tokens)
    assert context_error(request) is None


@pytest.mark.parametrize("max_tokens", [0, -1, MAX_REPLY_TOKENS + 1])
def test_history_reply_token_limits_reject_out_of_range_values(max_tokens):
    request = ChatRequest(message="next", history=[], max_tokens=max_tokens)
    assert context_error(request) is not None


def test_legacy_requests_keep_sampling_and_multimodal_behavior():
    assert MAX_CHAT_BODY_BYTES == 65536
    legacy_text = ChatRequest(message="legacy prompt", max_tokens=0)
    legacy_multimodal = ChatRequest(
        message=[
            {"type": "text", "text": "describe this"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
        ]
    )

    assert legacy_text.history is None
    assert legacy_text.max_tokens == 0
    assert context_error(legacy_text) is None
    assert legacy_multimodal.message[0]["type"] == "text"
    assert context_error(legacy_multimodal) is None


@pytest.mark.parametrize(
    "payload",
    [
        {"message": "next\ud800", "history": []},
        {"message": "next", "history": [{"role": "user", "content": "bad\ud800"}, {"role": "assistant", "content": "ok"}]},
        {"message": "legacy\ud800"},
    ],
)
def test_unpaired_surrogates_are_rejected_without_utf8_encoding_crashes(payload):
    with pytest.raises(ValidationError):
        ChatRequest(**payload)
