# Oratrice

[![Portable checks](https://github.com/leoxu0507-glitch/oratrice/actions/workflows/ci.yml/badge.svg)](https://github.com/leoxu0507-glitch/oratrice/actions/workflows/ci.yml)
![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![Status](https://img.shields.io/badge/status-v0.1%20degraded-orange)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Oratrice is a local-first, provider-neutral AI core for personal assistants.
It gives desktop pets, Web clients, and command-line tools one stable API while
keeping local runtimes, model gateways, and opt-in cloud providers replaceable.

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
providers.  Routing is deterministic and cloud fallback is opt-in.

> **Project status:** V0.1 is usable on its validated Windows host, but remains
> marked **DEGRADED** while launcher process-reaping evidence and hardware
> headroom are incomplete. See [Project overview](docs/PROJECT-OVERVIEW.md).

## v0.2 candidate (acceptance blocked)

The generated default profile selects the local GPT-OSS text chain and Gemma
router. Cloud inference is not enabled implicitly; it requires explicit policy
and credentials. Qwen-VL remains optional and deferred.

- **M9 lifecycle:** shutdown failures retain process ownership, interrupted
  startup rolls back, Windows supervision covers child processes, and chat and
  route share an admission slot per API instance. Offline integration and
  surrogate-process checks passed; real-model restart and normal user-console
  acceptance remain pending. See the
  [M9 ledger](docs/validation/M9-RELEASE-SUMMARY.md).
- **M10 portable installation:** a clean Windows/Python 3.13.5 checkout passed
  Core and Gateway installation and CheckOnly, strict Doctor, dry-run, and 180
  offline tests. These are historical M10 results; the v0.2 candidate CI and
  installation gates still need release-owner results. See [Windows environment
  setup](docs/architecture/ENVIRONMENT.md) and the
  [M10 ledger](docs/validation/M10-RELEASE-SUMMARY.md).
- **M11 recent conversation:** the Web UI sends successful recent turns in
  page memory, with at most 12 prior messages and a 1536-unit budget (UTF-8
  content bytes plus 32 framing units per message); replies are capped at 256
  tokens. Refresh and New conversation reset context. There is no persistence
  or streaming. The recorded 211-test Python suite, 11 JavaScript behavior
  checks, and Edge API acceptance used an injected provider; real-model
  acceptance remains pending. See the
  [M11 ledger](docs/validation/M11-RELEASE-SUMMARY.md) and
  [chat contract](docs/architecture/API.md).

Real-model chat, Ctrl+C cleanup, and clean installation passed. The required
restart failed, and process private memory rose during the 30-minute run;
window-close acceptance remains deferred. Stable v0.2 is blocked. See the
[v0.2 candidate notes](docs/releases/v0.2.0.md).

- M1: validated YAML configuration, resource registry, local llama.cpp and
  LiteLLM adapters, and the local-first model profile.
- M2: one-click Windows launcher with health-gated process ownership and
  cleanup.
- M3: declarative routing policy for text/chat, vision/OCR, and complex
  reasoning candidates.
- M4: provider-neutral FastAPI boundary with `/chat`, `/route`, and `/health`.
  The live launcher starts the API after GPT-OSS, Gemma Router, and LiteLLM.
- M5: offline release gate, runtime alias resolution, profile propagation,
  liveness semantics, transport-error mapping, and consolidated documentation.
- M6: explicit release/health contracts, portable launcher discovery, offline
  doctor, reproducible project-environment bootstrap, and an OpenAI-compatible
  design boundary.  Its release candidate was historically **BLOCKED** by a
  broken LiteLLM venv.
- M7: rebuilt separate project/LiteLLM environments, rewired the live profile,
  verified every required component, fixed cross-process readiness at the API
  adapter, and passed the real Launcher → Gemma → LiteLLM → GPT-OSS → Core API
  chain.  The live required chain is **PASS**; overall M7 is **DEGRADED** only
  for bounded-regression and tight hardware-headroom caveats.  See the
  [project overview](docs/PROJECT-OVERVIEW.md).
- M8: added the bundled thin same-origin Web UI at `/ui/`, made it the
  launcher-default entry point, hardened LiteLLM payload logging, and made
  public response model IDs preserve the caller's configured alias instead of
  exposing an internal transport path.  The M8 functional regression reached
  `150 passed` on Attempt 2; the final Attempt 3 found one documentation phrase
  incompatibility, which was corrected without a prohibited fourth run.  The
  required M8 live feature path is **PASS**.  Overall V0.1 remains
  **DEGRADED** because Codex ConPTY Ctrl+C closed listeners but did not reap
  launcher-owned processes. Two bounded handler variants also failed their
  lightweight ignore-SIGINT harness and were reverted as unverified; only the
  original Job Object source was shipped in the M8 snapshot. Hardware headroom is small. See the
  [M8 release summary](docs/validation/M8-RELEASE-SUMMARY.md).

See the [project overview](docs/PROJECT-OVERVIEW.md) for the full milestone
history, architecture, validation ledger, deferred provider paths, and
maintenance guidance.

The default Oratrice UI is the bundled same-origin page at
`http://127.0.0.1:8000/ui/`.  OpenWebUI remains an optional external UI for a
custom profile; Oratrice does not install, configure, or own it.

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
profile at a different `--output`/`--gateway-output` location. Consult the
validation ledger before loading large models on a memory-constrained host.

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

## Core API

The API binds to loopback by default:

```text
GET  http://127.0.0.1:8000/live
GET  http://127.0.0.1:8000/ready
GET  http://127.0.0.1:8000/health
POST http://127.0.0.1:8000/chat
POST http://127.0.0.1:8000/route
GET  http://127.0.0.1:8000/ui/
```

The bundled UI is a deliberately thin same-origin client.  It calls `/live`
and `/ready` for status and `/chat` for normal conversation; it does not call
`/route` for a normal chat, persist conversation state across reloads, or contain model,
provider, memory, tool, agent, voice, vision, cloud, or streaming logic.  The
desktop pet can consume status/notification information later without
duplicating the Core contract.

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
& $env:ORATRICE_PYTHON -m pytest -q
node --test tests/web_chat.test.cjs
```

The separate M11 JavaScript gate uses Node's built-in runner with inert
browser/HTTP fakes; no npm packages or frontend build are needed. The running
Web UI itself requires only a browser. See [Testing](docs/architecture/TESTING.md).

M7's historical full-suite path stopped at the three-attempt boundary with
`139 passed / 2 failed / 0 errors`; both remaining failures were BOM markers
removed statically after the limit.  M8 then ran a fresh full-suite path: attempt
1 reached `149/150` before the M8 boundary fix, and attempt 2 passed `150 tests
in 2.08s`.  M8 focused checks and live evidence are recorded separately in
`docs/validation/M8-08-REAL-CHAIN.md`; live requests must not be merged with
offline pytest counts.

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
