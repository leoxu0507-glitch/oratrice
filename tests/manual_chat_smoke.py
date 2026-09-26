"""Opt-in smoke check for a running local model endpoint.

This module is intentionally not named ``test_*.py`` and is never collected by
pytest.  It is a human-operated check for a developer who already has
llama.cpp (or another OpenAI-compatible local server) running.  No cloud
credentials are read.

Example::

    python tests/manual_chat_smoke.py --base-url http://127.0.0.1:8080
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.llama_cpp import LlamaCppProvider


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--model", default="gpt-oss")
    parser.add_argument("--message", default="Hello, introduce yourself.")
    args = parser.parse_args()

    provider = LlamaCppProvider(args.base_url)
    print(provider.chat(args.model, args.message))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
