# Oratrice project overview

This document summarizes the M1-M12 delivery history, current architecture,
and accepted limitations. Test counts refer only to recorded validation runs;
live model evidence and offline pytest results are intentionally kept separate.

## Product vision

Oratrice is a local-first, provider-neutral personal AI core. It gives desktop,
CLI, and Web frontends one stable API while keeping model runtimes, gateways,
and cloud providers replaceable behind explicit contracts.

The Core does not depend on a concrete model vendor. Gemma acts as a routing
model, not as the final conversational model. LiteLLM is the gateway boundary,
GPT-OSS is the default local text model, Qwen-VL is an optional deferred vision
path, and DeepSeek is an opt-in cloud candidate. The generated default profile
contains the local text chain only. Cloud inference is not enabled implicitly;
the optional cloud example is separate and requires explicit configuration and
credentials. Qwen-VL remains deferred.

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

The main boundaries are:

- `core/`: configuration, composition, facade, registries, and lifecycle.
- `router/`: structured route decisions and policy evaluation only.
- `providers/`: transport-neutral provider contracts and adapters.
- `launcher/`: ordered startup, readiness gates, reuse, and owned-process
  cleanup.
- `oratrice_api/`: strict FastAPI DTOs, safe errors, and health endpoints.
- `frontends/web/`: a thin same-origin client with no model or provider logic.

## Milestone summary

| Milestone | Delivered | Result |
| --- | --- | --- |
| M1 | Configuration, registry, llama.cpp and LiteLLM adapters, local profile, direct Qwen-VL smoke | Required local path PASS; gateway vision deferred |
| M2 | Declarative launch plan, orchestrator, CLI, Windows launcher | Offline orchestration and dry-run PASS |
| M3 | Capability-aware routing policy and Gemma composition | Composition gate PASS; router remains decision-only |
| M4 | `/chat`, `/route`, `/health`, lifecycle, safe API errors | API and launcher/API gates PASS |
| M5 | Offline release gate, alias resolution, profile propagation, transport mapping | Release gate PASS within the bounded attempt ledger |
| M6 | Release/health contracts, doctor, portable launcher, environment bootstrap | Historically blocked by the LiteLLM environment |
| M7 | Rebuilt isolated environments, cross-process readiness, real required chain | GPT-OSS/Gemma/LiteLLM/Core live chain PASS; overall DEGRADED for resource caveats |
| M8 | Bundled Web UI, logging hardening, public aliases, release validation | Required functional chain PASS; V0.1 overall DEGRADED |
| M9 | Truthful lifecycle shutdown, interrupted-start rollback, Windows process supervision, per-instance chat/route admission | Historical M9 result: offline integration and surrogate-process checks PASS; real-model restart and user-console acceptance were deferred at that milestone |
| M10 | Generated local configuration, isolated Gateway installation, strict offline diagnostics, portable CI definition | Historical M10 result: clean Windows/Python 3.13.5 install checks and 180 offline tests PASS; remote CI was not part of that validation and hardware stability remained deferred |
| M11 | Bounded recent conversation, request limits, reset and recoverable UI behavior | Historical M11 result: 211 Python tests and 11 JavaScript checks passed; Edge acceptance used an injected provider; real-model acceptance was deferred |
| M12 | Real-use acceptance, liveness-probe repair, disabled default RAM prompt cache, and startup-failure diagnostics | Installation/cold-start/chat/browser/Ctrl+C checks PASS within recorded scope; local full Python regression `220 passed`. Real-model restart and soak acceptance BLOCKED; repair not verified with real models. [M12 ledger](validation/M12-RELEASE-SUMMARY.md) |

## Current request path

```text
Web UI -> Core API -> CoreFacade -> Gemma Router -> LiteLLM -> GPT-OSS
```

The default required startup order is GPT-OSS on port 8080, Gemma Router on
8090, LiteLLM on 4000, and Core API on 8000. The bundled UI is served from
`/ui/` by the Core API, so it adds no process or port.
This is the generated default local-text deployment. Cloud use requires an
explicit configuration choice and credentials; the optional cloud example is
not merged into the default profile.

## Validation snapshot

- Historical M9 integrated offline suite: `163 passed`; native process
  supervision used surrogate child processes. At M9, real-model restart and
  normal user-console acceptance were deferred.
- Historical M10 clean Windows/Python 3.13.5 checkout: Core and Gateway
  installation, strict Doctor, dry-run, and `180 passed`.
- Historical M11 integrated suite: `211 passed` in Python and `11 passed` in the
  separate JavaScript behavior gate. Edge UI/API acceptance used an injected
  provider. No local JavaScript rerun was needed for the later launcher/configuration
  repair follow-up.
- M12 real cold-start, chat, browser, and Ctrl+C cleanup passed within the
  recorded automated scope; the real-model restart failed to reach readiness.
  The 30-minute soak completed 30 requests over 1801.5 seconds, but process
  private commit grew by `596.7 MiB`; restart and sustained-memory acceptance
  remain blocked. See the [M12 acceptance ledger](validation/M12-RELEASE-SUMMARY.md).
- The repair follow-up sets `--cache-ram 0` in default profiles, but no real
  model launch, restart, or sustained-use run followed that change. Native
  window-close/restart/cleanup checks using surrogate processes passed; they
  do not establish real-model behavior.
- The local full Python regression after repairs passed `220` tests. The
  JavaScript `11 passed` result is from an earlier gate and was not rerun
  locally for the repair follow-up.
  Baseline commit `416a537` passed [GitHub CI](https://github.com/leoxu0507-glitch/oratrice/actions/runs/41444082603); exact-checkout checks for current source are tracked in [PR #1](https://github.com/leoxu0507-glitch/oratrice/pull/1).
- M8's required live UI, readiness, routing, and chat path: PASS.
- Secrets, model weights, virtual environments, logs, and runtime output are
  excluded from the repository.

## Accepted limitations

1. The legacy live profile targets the maintainer's `D:\AI` layout.
   The generated local profile supports a portable setup, but Python, llama.cpp
   with compatible runtime DLLs, and model weights remain user-supplied.
   Installation evidence is specific to the recorded Windows/Python host.
2. Qwen-VL through LiteLLM remains deferred. Direct llama.cpp vision evidence
   does not prove the gateway path.
3. DeepSeek requires explicit cloud policy opt-in and `DEEPSEEK_API_KEY`; no
   cloud provider is selected implicitly by the generated default profile.
4. M9/M12 Windows supervision checks used surrogate child processes. The
   recorded M12 real-model restart failed before readiness; post-repair real-model
   restart, memory stability, and model-loaded window-close behavior remain
   unverified. M8's earlier ConPTY observations are historical evidence.
5. M11 context is recent and in-memory only: at most 12 prior messages, a
   1536-unit budget (UTF-8 content bytes plus 32 framing units per message),
   and a 256-token reply cap. Refresh or New conversation resets it. There is
   no persistence, automatic summary, or streaming. The API requires one
   worker for the default profile's single-model admission guarantee.
6. Measurements and soak evidence are limited to the tested host and settings.
   High concurrency, long contexts, continuous uptime, and simultaneous Qwen
   use are not validated for general hardware.

## Maintenance rules

- Add models and providers through configuration and adapter registries rather
  than branching in the Core.
- Keep the router decision-only and the Web UI API-only.
- Keep cloud use explicit and secrets environment-backed.
- Treat offline tests and live model validation as separate evidence.
- Preserve the three-attempt diagnostic limit for a single unchanged path.
- Do not call v0.2 accepted until real-model restart, post-fix memory
  stability, and model-loaded window-close acceptance pass, alongside required
  CI and installation checks.
- Do not introduce Memory, Tools, Agents, voice, or autonomous behavior as an
  incidental infrastructure change.
