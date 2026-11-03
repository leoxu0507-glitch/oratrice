"""Run the standalone Oratrice status companion."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from .app import run_app
from .client import DEFAULT_BASE_URL


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oratrice-pet",
        description="Show local Oratrice service status in a small desktop window.",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=(
            "loopback HTTP(S) origin only (localhost, 127.x.x.x, or ::1); "
            f"default: {DEFAULT_BASE_URL}"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        return run_app(arguments.base_url)
    except (ValueError, RuntimeError) as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
