# M6-06 controlled real-chain validation

- **Date:** 2026-08-16 (UTC)
- **Canonical checkout:** `D:\AI\projects\Oratrice`
- **Scope:** required local chain only: GPT-OSS, Gemma Router, LiteLLM Gateway, and Core API. `--no-browser`; no Qwen-VL and no DeepSeek key.
- **Disposition:** **BLOCKED (setup)**

The live path could not reach the first health gate. The configured LiteLLM
venv is broken: `D:\AI\infrastructure\litellm\.venv\pyvenv.cfg` points to
`<USER_PROFILE>\AppData\Local\Programs\Python\Python313\python.exe`, but
that base installation is absent. Running the configured venv Python exits
with code 101 (`Unable to create process`). This is a required prerequisite
failure under the release contract; no HTTP request or model load was
attempted.

## Preflight and cleanup sentinels

At `2026-08-16T04:54:18.752Z`, and again after the final attempt at
`2026-08-16T04:59:21.502Z`, all scoped listeners were absent:

| Port | Owner before | Owner after |
| ---: | --- | --- |
| 8080 (GPT-OSS) | none | none |
| 8090 (Gemma) | none | none |
| 4000 (LiteLLM) | none | none |
| 8000 (Core API) | none | none |
| 8082 (Qwen, out of scope) | none | none |
| 3000 (OpenWebUI, external) | none | none |

`nvidia-smi` reported one NVIDIA GeForce RTX 4060 Laptop GPU, 8,188 MiB
total, 10 MiB used, 7,947 MiB free (driver 610.74). The llama-server
executable and GPT-OSS/Gemma model files were present; the launcher and
LiteLLM executables/configuration were present. No related launcher, Python,
llama-server, uvicorn, or LiteLLM process remained after the attempts. Only
the launcher PID created by attempt 3 was observed, and it exited on its own;
there was nothing to terminate.

## Bounded attempts (maximum three)

| Attempt | UTC start | Command/setup | PID(s) and logs | Result / changed hypothesis |
| ---: | --- | --- | --- | --- |
| 1 | 04:55:41.941 | `Start-Oratrice.exe --no-browser` via PowerShell `Start-Process` with redirected stdout/stderr | No PID. Empty logs under `...\.m6_live_stage\attempt1\` | **BLOCKED/setup:** host environment contains duplicate case-insensitive `PATH`/`Path`; `Start-Process` rejected the environment dictionary before launch. |
| 2 | 04:56:18.927 | Same launcher, adding `-UseNewEnvironment` | No PID. No process/log files created under `...\.m6_live_stage\attempt2\` | **BLOCKED/setup:** the same duplicate `Path` key was raised before launch. This was not rerun as a model check; it tested whether the host-environment isolation switch avoided the setup error. |
| 3 | 04:56:53.067 | Manual `System.Diagnostics.ProcessStartInfo` launch of `Start-Oratrice.exe --no-browser` with redirected logs (no browser, no optional target) | Parent launcher PID **11084**; exited immediately. Logs: `<USER_PROFILE>\Documents\Codex\2026-08-03\oratrice-codex-oratrice-local-first-ai-2\.m6_live_stage\attempt3\launcher.stdout.log` and `launcher.stderr.log` | **BLOCKED/setup:** launcher reached its Python handoff, then stderr reported `Unable to create process using "D:\AI\infrastructure\litellm\.venv\Scripts\python.exe" ...`. The venv's base interpreter is missing. No child service PID or listener appeared. |

Attempt 3 used a different process-launch mechanism after the PowerShell
environment-dictionary failure. The host's `ProcessStartInfo.Environment`
map was unavailable, so the launcher inherited the shell environment; this
does not change the observed root cause (the configured venv Python itself is
not runnable). A working CodeX runtime Python was found read-only as a future
environment repair candidate, but it was **not** used because the three-attempt
limit was reached.

## Contract probes

No probes were sent because no required service started:

- GPT-OSS `GET /health`: **BLOCKED/setup**
- Gemma Router `GET /health`: **BLOCKED/setup**
- LiteLLM `GET /health/liveliness`: **BLOCKED/setup**
- Core API `GET /live`, `GET /health`, `GET /ready`, `POST /route`, `POST /chat`: **BLOCKED/setup**

There are no request IDs, aliases, HTTP statuses, prompts, or raw responses
to report. No process cleanup was necessary beyond confirming the scoped
ports and related process list were empty.

## Deferred scope

Qwen-VL, DeepSeek/cloud, and OpenWebUI remain **DEFERRED** by the requested
scope. They were not started, probed, or used as fallback paths.
