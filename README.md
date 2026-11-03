# Oratrice

[![Portable checks](https://github.com/leoxu0507-glitch/oratrice/actions/workflows/ci.yml/badge.svg)](https://github.com/leoxu0507-glitch/oratrice/actions/workflows/ci.yml)
![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![Status](https://img.shields.io/badge/status-v0.2%20local%20text%20accepted-brightgreen)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Oratrice is a local-first, provider-neutral core for a personal AI assistant.
Its bundled Web client supports bounded multi-turn text conversations through
a stable Core API. Local model runtimes, gateways, and explicitly enabled cloud
providers stay replaceable behind configuration and adapter contracts. The
standalone status pet and future command-line frontends use the same API.

The project is built around one rule: orchestration belongs in the Core, model
selection belongs in the Router, and model-specific transport belongs behind a
Provider boundary.

## Why Oratrice?

- **Local first:** the default text path runs on the user's machine and cloud
  fallback requires explicit policy opt-in.
- **Provider neutral:** Core contracts do not depend on GPT-OSS, Qwen,
  DeepSeek, or a particular HTTP SDK.
- **Replaceable infrastructure:** models, providers, routes, and policies are
  selected through typed configuration and registries.
- **One stable surface:** FastAPI exposes chat, routing, liveness, readiness,
  health, and the bundled Web client.
- **Operationally honest:** offline tests, live model evidence, deferred paths,
  and known limitations are documented separately.

## Architecture

```text
Desktop pet / Web UI / CLI
            |
            v
       Oratrice Core
            |
            v
   Gemma Router + Policy
            |
            v
 Provider Manager / LiteLLM
       |        |        |
       v        v        v
   GPT-OSS   Qwen-VL   Cloud API
    local    optional    opt-in
```

The composition root (`core.application.build_application`) wires concrete
providers. Policy validation enforces configured capabilities and explicit
cloud opt-in.

## Current status

[v0.2.0](https://github.com/leoxu0507-glitch/oratrice/releases/tag/v0.2.0) is the
accepted local-text release for the recorded Windows configuration. It adds
bounded multi-turn chat, portable setup, and verified real-model lifecycle
behavior while preserving the [v0.1.0](https://github.com/leoxu0507-glitch/oratrice/releases/tag/v0.1.0)
history.

| Area | Verified scope |
| --- | --- |
| Core | Provider-neutral configuration, registries, routing, facade, lifecycle, and HTTP contracts |
| Installation | Fresh isolated Python 3.13.5 Core/Gateway environments, LiteLLM 1.74.3, generated local-only configuration, strict Doctor, and dry-run |
| Real conversation | Core API context checks and nine bundled Web UI checks, including reset, actual busy recovery, refresh, duplicate protection, and keyboard send |
| Lifecycle | Cold readiness in 40.70 s, restart in 37.68 s, and real Ctrl+C / classic-console close cleanup; observed owned processes reaped and required ports free before the outer finalizer |
| Sustained use | 1800 s, 24 sequential question/follow-up pairs, and 51 controller chat requests overall, all HTTP 200. Median 15.496 s, maximum 20.033 s. |
| Offline gates | 276 Python tests (one dependency warning) and 11 JavaScript tests passed. Release checks are linked from the PR and release. |

The operator explicitly chose to observe Windows available physical RAM rather
than abort solely on that counter. It reached 77.7 MiB during sustained use,
but the full workflow completed without a request failure or crash. Combined
tracked private commit rose 56.1 MiB over the session; the final 13 samples
rose 19.4 MiB, within the recorded bounds. This is a bounded 30-minute result,
not a claim of leak-free continuous uptime or compatibility with all hardware.
All earlier guarded stops remain in the acceptance ledger.

- [Project overview](docs/PROJECT-OVERVIEW.md): architecture, history, and limits.
- [M12 acceptance record](docs/validation/M12-RELEASE-SUMMARY.md): criteria,
  measurements, earlier stopped runs, and the completed real-use pass.
- [v0.2 release notes](docs/releases/v0.2.0.md): validated scope and requirements.
- [Roadmap](docs/PROJECT-OVERVIEW.md#next-work-proposed-sequence): completed
  M13-M15 conversation, streaming, and status work, plus remaining proposals.

The bundled same-origin UI is `http://127.0.0.1:8000/ui/`. The generated default
profile is local-only, with no implicit cloud fallback. Qwen-VL and cloud
inference remain optional, separately unaccepted paths. OpenWebUI is external
and is not installed or owned by Oratrice.

### Development: M13-M15 conversation and status controls (unreleased)

The current source adds a visible UTF-8 context budget, incomplete-reply
labels, and local Markdown/JSON export of successful turns. These additions
are not included in the existing v0.2.0 release assets.

Chat remains page-only by default. Enable **Automatically save chats in this
browser** to retain conversations across refreshes and browser restarts.
Saved chats can be opened, deleted, or cleared. Turning saving off retains
existing records until deletion; exports provide a portable backup.

Retention uses unencrypted browser `localStorage`, scoped to the exact
origin and browser profile. For example, `localhost` and `127.0.0.1` do not
share records. It is limited to 20 conversations, 1 MiB total serialized
data, and 128 KiB per record. Browser Web Locks are required for writes;
page-only chat and export remain available if saving fails. The interface
reports quota, corruption, and cross-tab conflicts without silently evicting
conversations or overwriting another tab's edits.

Stored history does not enlarge the model context. The existing 12-prior-message,
1536-unit input budget and 256-token reply cap remain in force. An archive
over those limits opens for reading/export; start a new conversation to chat.
No model Memory, automatic summary, cloud storage, or transcript import is added.
See the [browser data contract](docs/architecture/API.md) for exact limits and
deletion/recovery behavior.

Enable **Stream replies as they arrive** for incremental text through
`POST /chat/stream`. This page-local option is off by default; ordinary `/chat`
remains available. **Stop reply** ends display immediately and preserves the
draft. The model may continue working, so Oratrice can remain busy until that
operation ends. Interrupted text is visibly partial and excluded from future
context, saved conversations, and exports. A normally completed reply with a
length-limit marker remains labeled incomplete, as in M13.

M14's local gates passed 305 Python and 56 JavaScript tests. A real local
Gemma/LiteLLM/GPT-OSS browser pass verified streamed text, follow-ups,
Stop/busy/recovery, and restart. In its first request, visible text began at
22.973 s and the answer completed at 25.000 s; streaming does not remove the
wait before the first text. See the [M14 evidence](docs/PROJECT-OVERVIEW.md#m14-incremental-replies-and-truthful-stop-behavior-implemented-unreleased)
for environment and scope. These are local development checks, not a new
published release or remote CI result.

M15 adds an independent status pet. Double-click `Start-Oratrice-Pet.cmd`, or
run `& .\.venv\Scripts\python.exe -m frontends.pet`. It shows service status
and offers **Open chat**; conversation stays in the Web UI. Closing the pet
leaves Core and models running. It uses standard-library Tk and a validated
loopback origin. See the [pet guide](frontends/pet/README.md) for controls.

Both frontends now read `GET /status`, including work continuing after Web
Stop. M15 local checks passed 372 Python and 63 JavaScript tests, actual
Tk/Edge/API integration with an injected provider, and a portable one-click
launch. The M14 real-model record remains separate. OpenPets integration is
deferred because the installed 3.2.1 plugin host rejects loopback HTTP access;
the operator selected this standalone companion. Existing OpenPets files and
settings were not modified.

## Install and configure on Windows

Use Python 3.13 for the validated dependency baseline. From your checkout root,
run the following commands, replacing the Python and model paths with your
actual files. Python, llama.cpp (including its runtime DLLs), and compatible
GPT-OSS/Gemma GGUF weights must be supplied separately.

```powershell
.\scripts\setup_oratrice.ps1 -Python 'C:\Python313\python.exe'
.\scripts\setup_oratrice.ps1 -Python 'C:\Python313\python.exe' -Gateway
& .\.venv\Scripts\python.exe .\scripts\configure_local.py `
  --llama-server 'C:\llama.cpp\llama-server.exe' `
  --gpt-model 'C:\Models\openai_gpt-oss-20b-MXFP4.gguf' `
  --router-model 'C:\Models\gemma-3n-E4B-it-Q5_K_M.gguf'
.\Start-Oratrice.exe doctor --strict-paths
.\Start-Oratrice.exe --dry-run --no-browser
```

Setup creates separate `.venv` (Core) and `.gateway-venv` (LiteLLM 1.74.3)
environments. Only these project environments are modified. The generator
creates ignored `config/profiles/local.yaml` and `config/gateway.local.yaml`,
refusing to overwrite existing files. Core/Gateway paths remain relative to
the project; external model paths remain absolute. No credential is saved.
The launcher generates an ephemeral gateway key if none is supplied.

The launcher, standalone API, and doctor prefer `local.yaml` when it exists;
`--profile` (launcher/doctor) and `ORATRICE_CONFIG` (standalone API) retain
explicit override control. Otherwise the legacy `live.yaml` remains the
fallback for the maintainer's existing installation.

The generated profile contains only the local text chain. Its context size
(2048), single server slot, CPU-first Gemma, GPU layers, and thread settings
are explicit configuration, not a hardware stability guarantee. Adjust them
with `--ctx-size`, `--gpt-gpu-layers`, and `--threads` when generating a new
profile at a different `--output`/`--gateway-output` location. GPT GPU layers
now default to `auto`, letting compatible llama.cpp builds fit device memory.
Use `--gpt-gpu-layers N` for an explicit non-negative layer count. Pinning a
large count such as `999` can prevent automatic fitting and exhaust VRAM;
check the installed runtime's `--help` for `--gpu-layers auto` support (checked
with b9843). Automatic device fitting does not reserve RAM for the router or
guarantee that both models fit the host. Existing profiles keep their values. The generated
GPT-OSS and Gemma runtimes explicitly disable the extra RAM-backed prompt
cache with `--cache-ram 0`. Use `--prompt-cache-mib N` to opt into a finite
per-model budget; two runtimes can each use that amount. This does not change
the Web UI recent-message contract. The flag was checked against llama.cpp
b9843 (`86b94708f`); use a runtime whose `--help` supports `--cache-ram`.
Existing generated/copied profiles are not rewritten: add `--cache-ram` and
`"0"` to both model runtimes' `args`, or generate a new profile at new output
paths. Consult the validation ledger before loading large models on a
memory-constrained host. The cache limit does not limit model-weight or GPU
allocations and is not proof that the real-use memory criterion now passes.

Inspect an existing installation without invoking pip:

```powershell
.\scripts\setup_oratrice.ps1 -Python 'C:\Python313\python.exe' -CheckOnly
.\scripts\setup_oratrice.ps1 -Python 'C:\Python313\python.exe' -Gateway -CheckOnly
```

## One-click startup

Run from the project directory:

```powershell
.\Start-Oratrice.exe --dry-run --no-browser  # plan only; starts nothing
.\Start-Oratrice.exe --no-browser           # start the local stack
.\Start-Oratrice.exe                        # start and open the bundled /ui/
.\Start-Oratrice.exe --profile config/profiles/live.yaml --with-qwen # legacy optional vision profile
```

The live required order is GPT-OSS (`8080`), Gemma Router (`8090`), LiteLLM
(`4000`), then Core API (`8000`).  After `/live` responds, the default launcher
probes and opens the bundled UI at `http://127.0.0.1:8000/ui/`.  Healthy
endpoints are reused; only launcher-owned processes are stopped on exit.
Press Ctrl+C in the launcher console, or close that console, to stop its owned
services. Closing the browser tab alone leaves the launcher and models running.
`--profile <path>` loads one resolved profile for both the launcher and the API
subprocess through the temporary `ORATRICE_CONFIG` environment value, which is
restored on exit.  A copied profile may point `ui_url` and `ui_health_url` at an
already-running external UI, but that UI remains outside Oratrice ownership.

A failed runtime reports its target, exception type, runtime state, and exit
code when available, for example `runtime_state=failed, returncode=23`.
Exception text, process arguments, and environment values are omitted from
that summary. For startup diagnosis, keep stdout and stderr in a local log:

```powershell
.\Start-Oratrice.exe --no-browser *> .\oratrice-startup.log
```

Treat that local log as private; model/runtime output may contain local paths
and request metadata. Avoid verbose model or gateway payload logging.

## Core API

The API binds to loopback by default:

```text
GET  http://127.0.0.1:8000/live
GET  http://127.0.0.1:8000/ready
GET  http://127.0.0.1:8000/health
GET  http://127.0.0.1:8000/status
POST http://127.0.0.1:8000/chat
POST http://127.0.0.1:8000/chat/stream
POST http://127.0.0.1:8000/route
GET  http://127.0.0.1:8000/ui/
```

The bundled UI is a same-origin client for `/status`, ordinary `/chat`, and
optional `/chat/stream`. Page-only history remains the default, with opt-in
browser retention and exports in the development source. The status pet reads
`/status` and opens `/ui/`. Neither frontend selects providers, starts models,
or implements model Memory, Tools, or Agents. `/live`, `/ready`, and `/health`
retain their existing diagnostic contracts.

Example chat request:

```json
{"message": "Hello", "capabilities": ["text"]}
```

Example route request:

```json
{"message": "Read this image", "requires_vision": true}
```

The DTOs reject unknown fields and responses omit prompts, raw transport
payloads, credentials, and exception causes.  `/live` always returns HTTP 200
for process liveness only.  `/ready` returns HTTP 200 when required readiness
is satisfied (including a degraded optional component) and HTTP 503 when a
required component is missing or unhealthy.  `/health` remains the compatible
diagnostic endpoint and always returns HTTP 200; inspect its JSON
`healthy`/`status` fields for dependency diagnostics.  In the live API,
`/ready` probes only `defaults.launcher.targets`; unselected optional targets
remain deferred instead of degrading the default stack.

## Environment and secrets

- `ORATRICE_PYTHON`: optional absolute Python executable selected by
  `Start-Oratrice.exe`; it must contain all requirements.
- `ORATRICE_CONFIG`: optional profile path for standalone API runs.  The
  launcher temporarily sets it from `--profile` and restores the previous
  value.
- `ORATRICE_LITELLM_MASTER_KEY`: LiteLLM gateway key.  The launcher generates
  a process-local value when absent and never prints or persists it.
- `DEEPSEEK_API_KEY`: optional cloud credential.  It is not needed for the
  default local-only routes and is never committed to YAML.

Keep credentials in the process environment or a secret manager.  The default
profile binds every service to `127.0.0.1`; do not expose these ports without
adding an intentional authentication and network boundary.

LiteLLM 1.74.3 is configured for metadata-only logging: payload logging is
disabled, raw request/response logging is disabled, and message/API-key
redaction is enabled.  The launcher supplies `LITELLM_LOG=WARNING` through the
live profile.  The M7 raw-output observation is retained in the historical
validation record; M8's privacy focused checks passed.  Do not treat logging
hardening as a substitute for keeping credentials out of prompts or reports.

## Deferred and optional paths

Qwen-VL is disabled by default because it is an explicit vision path with
additional VRAM pressure; use `--with-qwen` only after a hardware smoke check.
DeepSeek is transported through LiteLLM but requires an explicit cloud policy
opt-in and `DEEPSEEK_API_KEY`.  Neither path is part of the local-only default.

## Offline tests and release validation

The ordinary pytest suite is designed not to start a process, open a socket,
load model weights, or contact a cloud endpoint:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
node --test tests/web_chat.test.cjs
```

The separate M11 JavaScript gate uses Node's built-in runner with inert
browser/HTTP fakes; no npm packages or frontend build are needed. The running
Web UI itself requires only a browser. See [Testing](docs/architecture/TESTING.md).

The latest local repair regression passed 220 Python tests. Historical test
counts and hardware observations remain in their milestone ledgers. CI reports
its own exact checkout result; an offline pass does not accept real-model
restart, shutdown, or sustained memory behavior. See the
[M12 acceptance record](docs/validation/M12-RELEASE-SUMMARY.md).

For an intentional local model request, use the non-collected helper only
against a server that you started yourself:

```powershell
& $env:ORATRICE_PYTHON tests/manual_chat_smoke.py `
  --base-url http://127.0.0.1:8080 `
  --model gpt-oss `
  --message "Hello, introduce yourself."
```

## Project governance

- [Authors](AUTHORS.md)
- [Contributing guide](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Changelog](CHANGELOG.md)
- [MIT License](LICENSE)

Model weights, provider credentials, virtual environments, logs, and generated
runtime output are intentionally excluded from the repository. Oratrice is
created and maintained by **Stellamurus** with **OpenAI Codex** credited as the
second author and AI engineering collaborator; see `AUTHORS.md` for the exact
attribution.

## License

Oratrice is released under the [MIT License](LICENSE).
