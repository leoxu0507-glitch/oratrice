"""Opt-in, read-only evidence collection for the M12 acceptance procedure.

Prepare is offline. Observe/cleanup require --live and never start, signal,
or kill a process, send inference, or decide that the release is accepted.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import sys
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.configuration import ConfigurationLoader
from launcher.plan import LaunchPlan


class EvidenceError(ValueError):
    """An invalid or incomplete evidence operation; messages contain no input."""


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_path(path: Path) -> Path:
    resolved = path.resolve()
    work = (PROJECT_ROOT / "work").resolve()
    if resolved == work or not resolved.is_relative_to(work):
        raise EvidenceError("Use a new run directory below the checkout's work directory")
    return resolved


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _local_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "http" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise EvidenceError("Acceptance endpoints must be plain loopback HTTP URLs")
    host = parsed.hostname or ""
    if host != "localhost" and not ipaddress.ip_address(host).is_loopback:
        raise EvidenceError("Acceptance endpoints must use loopback")
    _ = parsed.port  # Validate the port before any observation.
    return value


def prepare(profile: Path, output: Path, *, revision: str, attempt: int,
            hypothesis: str, kind: str, soak_minutes: int) -> dict:
    """Create a fresh private record without network, process, or DLL calls."""
    if not re.fullmatch(r"[0-9a-fA-F]{40}", revision):
        raise EvidenceError("Supply the full source revision")
    if attempt not in (1, 2, 3) or not hypothesis.strip():
        raise EvidenceError("An attempt from 1 to 3 and a changed hypothesis are required")
    if kind not in {"real", "surrogate"} or not 30 <= soak_minutes <= 60:
        raise EvidenceError("Choose real/surrogate evidence and a 30-60 minute observation window")
    output = _run_path(output)
    profile = profile.resolve(strict=True)
    name = "ORATRICE_LITELLM_MASTER_KEY"
    had_key = name in os.environ
    if not had_key:
        os.environ[name] = "offline-acceptance-placeholder"
    try:
        plan = LaunchPlan.from_configuration(ConfigurationLoader(profile).load())
    finally:
        if not had_key:
            os.environ.pop(name, None)
    endpoints = []
    for target in plan.targets:
        if not target.health_endpoint:
            raise EvidenceError("Every required target needs an explicit health endpoint")
        endpoints.append({"target": target.id, "url": _local_url(target.health_endpoint)})
    if not endpoints:
        raise EvidenceError("The acceptance profile needs required launch targets")
    record = {
        "schema_version": 1, "evidence_kind": kind, "release_disposition": "DEFERRED",
        "prepared_at": utc(), "revision": revision, "attempt": attempt,
        "hypothesis": hypothesis, "profile": str(profile), "profile_sha256": _hash(profile),
        "collector_sha256": _hash(Path(__file__)), "python": sys.version.split()[0],
        "soak_minutes": soak_minutes, "endpoints": endpoints, "ui_url": _local_url(plan.ui_url),
        "observations": [], "checkpoints": [], "tracked": [], "roots": [], "cleanup": [],
        "identity_gaps": [], "source_state": "operator-declared",
        "logs": {phase: {stream: f"{phase}.{stream}.log" for stream in ("stdout", "stderr")}
                 for phase in ("cold-start", "restart")},
    }
    output.mkdir(parents=True, exist_ok=False)
    save(output, record)
    return record


def save(run: Path, record: dict) -> None:
    temporary = run / "evidence.json.tmp"
    temporary.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(run / "evidence.json")


def load(run: Path) -> tuple[Path, dict]:
    run = _run_path(run)
    record = json.loads((run / "evidence.json").read_text(encoding="utf-8"))
    if record.get("schema_version") != 1:
        raise EvidenceError("Unsupported evidence schema")
    # Validate persisted URLs again before network use, even in a local record.
    for endpoint in record["endpoints"]:
        _local_url(endpoint["url"])
    return run, record


def listeners(endpoints: list[dict]) -> list[dict]:
    """TCP listener observations only; this is not health or readiness."""
    results = []
    for endpoint in endpoints:
        parsed = urlsplit(_local_url(endpoint["url"]))
        try:
            with socket.create_connection((parsed.hostname, parsed.port or 80), timeout=0.5):
                state = "listening"
        except ConnectionRefusedError:
            state = "free"
        except OSError:
            state = "unknown"
        results.append({"target": endpoint["target"], "state": state})
    return results


def _windows():
    if os.name != "nt":
        raise EvidenceError("Live process observation requires Windows")
    from scripts import acceptance_windows
    return acceptance_windows


def observe(run: Path, phase: str, launcher_pid: int | None = None) -> dict:
    run, record = load(run)
    if _hash(Path(record["profile"])) != record["profile_sha256"]:
        raise EvidenceError("Profile changed; preserve this run and prepare a separate record")
    native = _windows()
    row = {"at": utc(), "phase": phase, "listeners": listeners(record["endpoints"]),
           "memory": native.memory_snapshot(), "processes": []}
    if phase == "baseline":
        if launcher_pid is not None:
            raise EvidenceError("Baseline observation must precede launcher startup")
        row["status"] = "PASS" if all(x["state"] == "free" for x in row["listeners"]) else "BLOCKED"
    else:
        baselines = [x for x in record["observations"] if x["phase"] == "baseline"]
        if not baselines or baselines[-1]["status"] != "PASS":
            raise EvidenceError("Record a free-port baseline before launching")
        if not launcher_pid or launcher_pid <= 0:
            raise EvidenceError("Supply the PID returned when starting the owned launcher")
        root = native.process_identity(launcher_pid)
        if root.get("state") != "running":
            raise EvidenceError("Launcher identity is unavailable; no ownership inference made")
        roots = record["roots"]
        identity = (root["pid"], root["created"])
        if phase in {"cold-start", "restart"}:
            if roots and identity != (roots[-1]["pid"], roots[-1]["created"]):
                previous_cleanup = record["cleanup"][-1] if record["cleanup"] else {}
                if previous_cleanup.get("status") != "PASS" or previous_cleanup.get("root") != roots[-1]:
                    raise EvidenceError("Verify prior cleanup before recording another launcher")
            if not any((item["pid"], item["created"]) == identity for item in roots):
                roots.append({"pid": root["pid"], "created": root["created"]})
        elif not roots or identity != (roots[-1]["pid"], roots[-1]["created"]):
            raise EvidenceError("Launcher PID was reused or has not been recorded")
        row["processes"] = native.process_tree(launcher_pid)
        if not row["processes"]:
            raise EvidenceError("Process tree snapshot was empty; ownership is unverified")
        row["status"] = "OBSERVED"
        same_root = any(p.get("state") == "running" and
                        (p["pid"], p["created"]) == identity for p in row["processes"])
        if not same_root:
            # A root can exit and its PID can be reused between the two reads.
            # Do not adopt the replacement process or its descendants.
            row["status"] = "BLOCKED"
            record["identity_gaps"].append({"at": row["at"], "pid": launcher_pid})
        for process in row["processes"] if same_root else []:
            if process.get("state") == "gone":
                continue
            if process.get("state") != "running":
                row["status"] = "BLOCKED"
                record["identity_gaps"].append({"at": row["at"], "pid": process["pid"]})
                continue
            key = (process["pid"], process["created"])
            if not any((p["pid"], p["created"]) == key for p in record["tracked"]):
                record["tracked"].append({"pid": process["pid"], "created": process["created"]})
    record["observations"].append(row)
    save(run, record)
    return row


def cleanup(run: Path, *, manual_intervention: bool) -> dict:
    """Observe exit only. Never signal, terminate, or reinterpret unknown PIDs."""
    run, record = load(run)
    if not record["tracked"]:
        raise EvidenceError("No observed owned-process identities to verify")
    native = _windows()
    survivors, unknown = [], []
    for original in record["tracked"]:
        current = native.process_identity(original["pid"])
        if current.get("state") == "gone":
            continue
        if (current.get("state") != "running" or type(current.get("created")) is not int
                or current["created"] <= 0):
            unknown.append(original)
        elif current["created"] == original["created"]:
            survivors.append(original)
    ports = listeners(record["endpoints"])
    passed = not survivors and not unknown and not record["identity_gaps"] and all(x["state"] == "free" for x in ports)
    row = {"at": utc(), "status": "PASS" if passed and not manual_intervention else "BLOCKED",
           "root": record["roots"][-1] if record["roots"] else None,
           "manual_intervention": manual_intervention, "survivors": survivors,
           "unknown": unknown, "identity_gaps": record["identity_gaps"],
           "listeners": ports, "memory": native.memory_snapshot()}
    record["cleanup"].append(row)
    save(run, record)
    return row


def checkpoint(run: Path, *, phase: str, result: str, note: str) -> dict:
    run, record = load(run)
    if not note.strip():
        raise EvidenceError("A checkpoint needs an observation note")
    row = {"at": utc(), "source": "operator", "phase": phase, "result": result, "note": note}
    record["checkpoints"].append(row)
    save(run, record)
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare", help="offline; create a fresh private evidence record")
    prep.add_argument("--profile", type=Path, required=True)
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--revision", required=True)
    prep.add_argument("--attempt", type=int, choices=(1, 2, 3), required=True)
    prep.add_argument("--hypothesis", required=True)
    prep.add_argument("--kind", choices=("real", "surrogate"), required=True)
    prep.add_argument("--soak-minutes", type=int, default=30)
    for command in ("observe", "cleanup", "checkpoint"):
        sub = commands.add_parser(command)
        sub.add_argument("--run", type=Path, required=True)
        if command != "checkpoint":
            sub.add_argument("--live", action="store_true", help="explicitly permit read-only OS/TCP observation")
        if command == "observe":
            sub.add_argument("--phase", choices=("baseline", "cold-start", "restart", "soak", "before-close"), required=True)
            sub.add_argument("--launcher-pid", type=int)
        elif command == "cleanup":
            sub.add_argument("--manual-intervention", action="store_true")
        else:
            sub.add_argument("--phase", choices=("chat", "browser", "soak", "restart-chat", "console-close", "failure-recovery"), required=True)
            sub.add_argument("--result", choices=("PASS", "FAIL", "DEFERRED"), required=True)
            sub.add_argument("--note", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in {"observe", "cleanup"} and not args.live:
            raise EvidenceError("OS/TCP observation requires explicit --live")
        if args.command == "prepare":
            row = prepare(args.profile, args.output, revision=args.revision, attempt=args.attempt,
                          hypothesis=args.hypothesis, kind=args.kind, soak_minutes=args.soak_minutes)
            status = "PREPARED"
        elif args.command == "observe":
            row = observe(args.run, args.phase, args.launcher_pid)
            status = row["status"]
        elif args.command == "cleanup":
            row = cleanup(args.run, manual_intervention=args.manual_intervention)
            status = row["status"]
        else:
            row = checkpoint(args.run, phase=args.phase, result=args.result, note=args.note)
            status = "RECORDED"
        print(json.dumps({"operation": args.command, "status": status, "release_disposition": "DEFERRED"}))
        return 1 if status == "BLOCKED" else 0
    except Exception as error:
        # No raw paths, endpoint contents, exception payloads, or operator notes.
        summary = {"operation": args.command, "status": "ERROR", "error_type": type(error).__name__}
        if isinstance(error, EvidenceError):
            summary["message"] = str(error)
        print(json.dumps(summary))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
