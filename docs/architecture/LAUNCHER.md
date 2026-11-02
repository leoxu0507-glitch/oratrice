# Oratrice launcher (M8)

## M9 lifecycle hardening

The M9 bootstrap creates Python suspended, assigns it to the kill-on-close
Job Object, and only then resumes it. Safety-job creation or assignment failure
aborts startup instead of continuing without supervision. Redirected failures
return an error without waiting for console input. Build a review candidate
with `scripts/build_launcher.ps1`; the default output is under ignored `work/`.

Python shutdown now preserves ownership when termination cannot be confirmed,
and `RuntimeStopError` prevents false `STOPPED` status. Bulk cleanup attempts
runtimes in reverse order. Interrupted startup rolls back owned resources;
cleanup failure restores environment state and produces CLI exit code 2.

Use `Start-Oratrice.exe` for the Windows process-tree safety boundary. Running
the Python CLI directly does not establish that native Job Object. Closing
the browser page leaves the launcher running; stop the launcher from its
console when the stack is no longer needed. Normal interactive console and
real-model restart acceptance are still pending, as recorded in the
[M9 ledger](../validation/M9-RELEASE-SUMMARY.md). The M8 findings below remain
historical and are not overwritten by lightweight M9 evidence.

`Start-Oratrice.exe` is a thin Windows bootstrap. It selects an existing Python
runtime and executes `scripts/launch_oratrice.py`; model, provider, port, health,
and ordering decisions remain in `config/profiles/live.yaml`.

Default startup order is GPT-OSS, Gemma Router with a launch-only `-ngl 0`
override, LiteLLM, then the Oratrice Core API. Use `--with-qwen` to insert
Qwen-VL before LiteLLM.
Qwen is not enabled by default because its LiteLLM vision route was deferred in
M1 and this host has 8 GB VRAM.

The launcher generates a process-local LiteLLM master key when none is supplied;
it never prints or persists the value. Healthy pre-existing services are reused
but never adopted or stopped. Required failures roll back only launcher-owned
processes. The Windows bootstrap uses a kill-on-close Job Object as an additional
process-tree safety boundary.

The Core HTTP API is now a required launcher target after LiteLLM. It runs from
the configured `oratrice_api.main:app` ASGI application on `127.0.0.1:8000` and
is health-gated at `/health`; an already healthy endpoint is reused. Once the
launcher reports `Oratrice API: READY`, it waits and lets the orchestrator own
cleanup on exit. The API process is separate from the in-process compatibility
Application, so the CLI does not construct a duplicate Application when the
Core API target is started or reused.

The repository-bundled thin UI is the default launcher destination. After the
Core API's `/live` probe succeeds, the launcher probes and opens
`http://127.0.0.1:8000/ui/`. The UI is served by the Core API's same-origin
static mount and does not add a process or port. `--no-browser` keeps the full
stack headless.

OpenWebUI remains an optional external UI. A copied profile may set
`ui_url`/`ui_health_url` to an already-running external service, but the
launcher does not install, configure, or own OpenWebUI or its Docker process.

Useful commands:

```powershell
.\Start-Oratrice.exe --dry-run
.\Start-Oratrice.exe
.\Start-Oratrice.exe --with-qwen
.\Start-Oratrice.exe --no-browser
```

The live profile's UI fields are declarative launcher metadata:

```yaml
defaults:
  launcher:
    ui_url: http://127.0.0.1:8000/ui/
    ui_health_url: http://127.0.0.1:8000/live
```

M8's offline UI/launcher contracts passed, and the live UI requests returned
HTTP 200. Cleanup behavior remains **DEGRADED**: in Codex ConPTY, Ctrl+C closed
listeners but did not reap launcher-owned processes. The managed-handler and
native-handler variants both failed their lightweight ignore-SIGINT harness;
both were exact-PID cleaned and their unverified changes were reverted. The
original Job Object source was restored and the executable was rebuilt at 8704
bytes with SHA-256
`46E12D87935017AB30CEC3EB7036E00F054D96A5DCADF3F6EDFE1D5F59E29085`;
dry-run passed. The cleanup investigation is stopped at the three-path limit.
The next milestone should redesign external lifecycle supervision or validate
the original path in a real user console before changing launcher code.
