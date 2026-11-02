"""Static checks that the bundled UI uses the Core chat limits."""

from __future__ import annotations

import re
from pathlib import Path

from oratrice_api.conversation import (
    MAX_CONTEXT_BYTES,
    MAX_HISTORY_MESSAGES,
    MAX_REPLY_TOKENS,
    MESSAGE_OVERHEAD_BYTES,
)


WEB_ROOT = Path(__file__).resolve().parents[1] / "frontends" / "web"


def test_web_chat_limits_match_the_core_contract():
    app_source = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    html_source = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

    limits = {
        "MAX_HISTORY_MESSAGES": MAX_HISTORY_MESSAGES,
        "MAX_CONTEXT_BYTES": MAX_CONTEXT_BYTES,
        "MESSAGE_OVERHEAD_BYTES": MESSAGE_OVERHEAD_BYTES,
        "MAX_REPLY_TOKENS": MAX_REPLY_TOKENS,
    }
    for name, value in limits.items():
        assert re.search(rf"\bconst\s+{name}\s*=\s*{value}\s*;", app_source)

    assert re.search(r"\bmax_tokens\s*:\s*MAX_REPLY_TOKENS\b", app_source)
    textarea = re.search(r"<textarea\b[^>]*\bmaxlength=[\"'](\d+)[\"']", html_source, re.IGNORECASE)
    assert textarea is not None
    assert int(textarea.group(1)) == MAX_CONTEXT_BYTES
