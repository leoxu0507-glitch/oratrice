# -*- coding: utf-8 -*-
"""Interactive CLI frontend.

The CLI owns presentation only.  Concrete providers, runtime lifecycle, and
route selection are wired by ``build_application`` and exposed through the
stable core facade.
"""

from pathlib import Path

from core.application import build_application


def main(config_path: str | Path | None = None):
    app = build_application(config_path=config_path)
    ai = app.facade

    print("\n========== Oratrice v1 ==========")
    print("Type 'exit' or 'quit' to quit.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye.")
            break

        if user_input.lower() in ("exit", "quit"):
            print("Bye.")
            break

        if not user_input:
            continue

        try:
            print("GPT-OSS: ", end="", flush=True)
            for chunk in ai.stream("model.gpt_oss", user_input):
                # CoreFacade returns normalized chunks; the compatibility
                # facade still yields strings for old integrations.
                print(getattr(chunk, "content", chunk), end="", flush=True)
            print()
        except Exception as e:
            print(f"\n[Error] {e}")


if __name__ == "__main__":
    main()
