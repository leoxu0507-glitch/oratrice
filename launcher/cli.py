"""Command-line entry point for the M2 one-click launcher."""

from __future__ import annotations

import argparse
import os
import secrets
import time
from collections.abc import Callable, MutableMapping, Sequence
from pathlib import Path
from typing import Any

from core.application import build_application
from core.configuration import ConfigurationLoader

from .orchestrator import LauncherOrchestrator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = PROJECT_ROOT / "config" / "profiles" / "live.yaml"
GATEWAY_KEY_ENV = "ORATRICE_LITELLM_MASTER_KEY"
CONFIG_PATH_ENV = "ORATRICE_CONFIG"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start the local Oratrice runtime stack")
    parser.add_argument(
        "command",
        nargs="?",
        choices=("doctor",),
        help="run an offline self-check instead of starting the runtime stack",
    )
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE))
    parser.add_argument("--dry-run", action="store_true", help="show the plan without side effects")
    parser.add_argument("--with-qwen", action="store_true", help="include the optional Qwen-VL runtime")
    parser.add_argument("--no-browser", action="store_true", help="do not open an available external UI")
    parser.add_argument(
        "--json",
        dest="doctor_json",
        action="store_true",
        help="doctor: emit machine-readable JSON (ignored for startup)",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="doctor: record a requested probe without performing network/port checks",
    )
    return parser


def _wait_forever() -> None:
    while True:
        time.sleep(1.0)


def _core_api_ready(result: Any) -> bool:
    """Return whether the launcher successfully started or reused Core API."""

    outcomes = getattr(result, "outcomes", ()) or ()
    return any(
        getattr(outcome, "id", None) == "core_api"
        and getattr(outcome, "status", None) in {"STARTED", "REUSED_EXTERNAL"}
        for outcome in outcomes
    )


def run(
    argv: Sequence[str] | None = None,
    *,
    orchestrator_factory: Callable[..., Any] = LauncherOrchestrator,
    application_factory: Callable[..., Any] = build_application,
    waiter: Callable[[], Any] | None = None,
    environ: MutableMapping[str, str] | None = None,
    output: Callable[[str], Any] = print,
) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    env = environ if environ is not None else os.environ
    profile_path = Path(args.profile).expanduser().resolve(strict=False)
    if args.command == "doctor":
        # Keep doctor before the launcher's secret/environment setup.  The
        # report is intentionally static: no application, orchestrator,
        # process, socket, browser, or model is created.
        from .doctor import run_doctor

        return run_doctor(
            profile_path,
            environ=env,
            probe=args.probe,
            json_output=args.doctor_json,
            output=output,
        )
    previous = env.get(GATEWAY_KEY_ENV)
    process_previous = os.environ.get(GATEWAY_KEY_ENV)
    process_had_key = GATEWAY_KEY_ENV in os.environ
    previous_config = env.get(CONFIG_PATH_ENV)
    process_previous_config = os.environ.get(CONFIG_PATH_ENV)
    process_had_config = CONFIG_PATH_ENV in os.environ
    generated = not bool(previous)
    orchestrator = None
    application = None
    if generated:
        env[GATEWAY_KEY_ENV] = (
            "oratrice-dry-run-local-placeholder"
            if args.dry_run
            else secrets.token_urlsafe(32)
        )
    # ConfigurationLoader intentionally resolves secrets from os.environ.
    # Mirror an injected embedding/test environment only for this call and
    # restore the process environment in the same finally block.
    os.environ[GATEWAY_KEY_ENV] = env[GATEWAY_KEY_ENV]
    # The API subprocess inherits the orchestrator environment.  Keep its
    # profile identical to the one loaded by this CLI invocation, including
    # when callers pass an injected mapping for tests or embedding.
    env[CONFIG_PATH_ENV] = str(profile_path)
    os.environ[CONFIG_PATH_ENV] = str(profile_path)
    try:
        configuration = ConfigurationLoader(profile_path).load()
        orchestrator = orchestrator_factory(configuration, env=env)
        optional = ["qwen_vl"] if args.with_qwen else []
        result = orchestrator.start(
            include_optional=optional,
            dry_run=args.dry_run,
            open_ui=not args.no_browser,
        )
        output("Oratrice launcher: " + result.status)
        for outcome in result.outcomes:
            output(f"  {outcome.id}: {outcome.status}")
        output("  UI: " + result.ui_status)
        if not result.ok:
            return 1
        if args.dry_run:
            return 0

        if _core_api_ready(result):
            output("Oratrice API: READY")
        else:
            application = application_factory(configuration=configuration, auto_start=False)
            output("Oratrice Core: READY (in-process; API deferred)")
        output("Press Ctrl+C to stop launcher-owned services.")
        try:
            (waiter or _wait_forever)()
        except KeyboardInterrupt:
            output("Stopping Oratrice...")
        return 0
    except KeyboardInterrupt:
        output("Stopping Oratrice...")
        return 0
    except Exception as exc:
        output("Oratrice launcher failed: " + type(exc).__name__)
        return 2
    finally:
        if application is not None:
            try:
                application.close()
            except Exception:
                pass
        if orchestrator is not None and not args.dry_run:
            try:
                orchestrator.stop()
            except Exception:
                pass
        if generated:
            env.pop(GATEWAY_KEY_ENV, None)
        elif previous is not None:
            env[GATEWAY_KEY_ENV] = previous
        if process_had_key and process_previous is not None:
            os.environ[GATEWAY_KEY_ENV] = process_previous
        else:
            os.environ.pop(GATEWAY_KEY_ENV, None)
        if previous_config is not None:
            env[CONFIG_PATH_ENV] = previous_config
        else:
            env.pop(CONFIG_PATH_ENV, None)
        if process_had_config and process_previous_config is not None:
            os.environ[CONFIG_PATH_ENV] = process_previous_config
        else:
            os.environ.pop(CONFIG_PATH_ENV, None)


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)


__all__ = ["CONFIG_PATH_ENV", "DEFAULT_PROFILE", "GATEWAY_KEY_ENV", "main", "run"]
