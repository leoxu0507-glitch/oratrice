"""Static M6-07 OpenAI-compatibility design contracts.

These checks read the design and route source only. They do not import the
FastAPI app, start a lifespan, start a process, open a socket, or contact a
provider.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs" / "architecture" / "OPENAI-COMPAT.md"
API_SOURCE = ROOT / "oratrice_api" / "app.py"


def _registered_routes(source: str) -> set[str]:
    """Read literal FastAPI decorator paths without importing the app."""

    tree = ast.parse(source, filename=str(API_SOURCE))
    routes: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            function = decorator.func
            if not (
                isinstance(function, ast.Attribute)
                and isinstance(function.value, ast.Name)
                and function.value.id == "api"
                and function.attr in {"get", "post", "put", "patch", "delete"}
            ):
                continue
            if decorator.args and isinstance(decorator.args[0], ast.Constant):
                value = decorator.args[0].value
                if isinstance(value, str):
                    routes.add(value)
    return routes


def test_design_declares_versioned_endpoints_and_response_fields() -> None:
    text = CONTRACT.read_text(encoding="utf-8")

    for phrase in (
        "POST /v1/chat/completions",
        "GET /v1/models",
        "messages",
        '"id"',
        '"object": "chat.completion"',
        '"created"',
        '"model"',
        '"choices"',
        'object: "list"',
        "data",
        "text/event-stream",
    ):
        assert phrase in text


def test_design_records_current_single_message_evidence_and_no_silent_flatten() -> None:
    text = CONTRACT.read_text(encoding="utf-8")

    for phrase in (
        "CoreFacade._request_args",
        "CoreFacade._chat_request",
        'ChatMessage(role="user"',
        "does not silently flatten",
        "does not register `/v1/chat/completions`",
        "M6",
    ):
        assert phrase in text

    for deferred in ("STREAM", "TOOLS", "VISION", "DEFERRED"):
        assert deferred in text


def test_current_api_has_no_accidental_openai_chat_registration() -> None:
    source = API_SOURCE.read_text(encoding="utf-8")
    routes = _registered_routes(source)

    assert "/v1/chat/completions" not in routes
    assert "/chat" in routes
    assert "/route" in routes
