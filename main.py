"""Oratrice application entry point.

Only the composition root is imported here; infrastructure details stay
behind the core facade and registry APIs.
"""

from pathlib import Path

from core.application import build_application


def main(config_path: str | Path | None = None):
    app = build_application(config_path=config_path)
    registry = app.registry

    print("\n========== Oratrice Resource Registry ==========\n")
    for category in ("runtimes", "models", "providers"):
        items = getattr(registry, f"list_{category}", lambda: [])()
        print(f"[{category.upper()}]")
        for item in items:
            print(f"  {getattr(item, 'id', item)}")
        print()
    return app


if __name__ == "__main__":
    main()
