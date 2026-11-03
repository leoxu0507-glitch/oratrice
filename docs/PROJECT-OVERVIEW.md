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
| M12 | Real-use acceptance, cache/diagnostic repairs, reproducible evidence collection, native listener tables, and automatic GPU fitting | PASS for default local text on the recorded host: real chat/UI, restart, Ctrl+C/console-close cleanup, and 1800-second sustained use. Offline code gate: 276 Python + 11 JavaScript tests. [M12 ledger](validation/M12-RELEASE-SUMMARY.md) |

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

- The fresh isolated installation passed Core/Gateway setup, dependency checks,
  strict Doctor, local configuration generation, and dry-run. The latest code
  gate passed 276 Python tests (one dependency deprecation warning) and 11
  JavaScript tests. Tested runtime source `3f9257f` passed
  [CI run 8](https://github.com/leoxu0507-glitch/oratrice/actions/runs/41571231563).
  Release-head checks are tracked in [PR #1](https://github.com/leoxu0507-glitch/oratrice/pull/1).
- Real cold readiness took 40.70 seconds and restart took 37.68 seconds.
  Core context, nine browser checks, normal Ctrl+C, and model-loaded classic
  console close passed. Both cleanup cycles reaped observed owned identities
  and freed required listeners before the outer controller finalizer.
- The sustained session completed 1800 seconds and 24 sequential short
  question/follow-up pairs. All 51 controller chat requests returned HTTP 200;
  median response was 15.496 seconds and maximum 20.033 seconds.
- Combined tracked private commit rose from 8384.6 to 8440.7 MiB (+56.1 MiB).
  The final 13 samples rose 19.4 MiB within the recorded 64-MiB growth and
  256-MiB range bounds. Working set fell 1711.8 MiB. These measurements are
  different from available physical RAM and do not establish long-term
  leak freedom.
- The operator explicitly removed free-physical-RAM numeric aborts before
  the successful pass. Minimum observed sustained available RAM was 77.7 MiB;
  actual requests and lifecycle completed. After exit, available RAM was
  9776.3 MiB and GPU use 721 MiB (baseline 8356.2 MiB / 733 MiB).
- Historical stopped/failed attempts, surrogate checks, and earlier suite
  counts remain in their [acceptance ledgers](validation/M12-RELEASE-SUMMARY.md).
  They are not retroactively changed into successful evidence.
- Model weights, credentials, environments, generated local profiles, and raw
  logs remain excluded from source and release bundles.

## Accepted limitations

1. The legacy live profile targets the maintainer's `D:\AI` layout.
   The generated local profile supports a portable setup, but Python, llama.cpp
   with compatible runtime DLLs, and model weights remain user-supplied.
   Installation evidence is specific to the recorded Windows/Python host.
2. Qwen-VL through LiteLLM remains deferred. Direct llama.cpp vision evidence
   does not prove the gateway path.
3. DeepSeek requires explicit cloud policy opt-in and `DEEPSEEK_API_KEY`; no
   cloud provider is selected implicitly by the generated default profile.
4. Real Ctrl+C and classic-console WM_CLOSE reaped owned processes on the
   tested host. Windows control-event exit codes do not prove that Python
   graceful-finally hooks ran. Other terminal hosts and embedding contexts
   require their own lifecycle checks; M8/M9 surrogate evidence is historical.
5. M11 context is recent and in-memory only: at most 12 prior messages, a
   1536-unit budget (UTF-8 content bytes plus 32 framing units per message),
   and a 256-token reply cap. Refresh or New conversation resets it. There is
   no persistence, automatic summary, or streaming. The API requires one
   worker for the default profile's single-model admission guarantee.
6. Measurements and soak evidence are limited to the tested host and settings.
   High concurrency, long contexts, continuous uptime, and simultaneous Qwen
   use are not validated for general hardware.

## Next work: proposed sequence

M12 default local-text acceptance passed under the recorded operator-directed
criteria. The following M13-M15 scopes remain proposals, not completed work.
Existing Core, router, provider, and launcher boundaries stay in place; use
configuration and existing ports when extending the product.

### M12 closeout: reproducible local acceptance and v0.2

The original and later guarded-attempt ledgers remain intact. After the
operator explicitly changed free-physical-RAM handling to observation, the
complete real-use pass succeeded. **R1-R4 default local-text acceptance: PASS.**
R5 uses exact-source CI, the preserved v0.1.0 history, and verified release
assets; the published release is the authority for that final operation.

| Task | Scope and owner boundary | Completion evidence |
| --- | --- | --- |
| M12-R1: Reproducible acceptance procedure | Validation scripts and operator docs: turn the machine-specific acceptance procedure into a parameterized, explicit opt-in procedure using a supplied profile. Preserve phase logs, exact process identities, and cleanup results; do not embed private paths or credentials. | Another clean checkout can follow the same procedure; offline/fake and surrogate checks are labeled separately from real-model evidence. The existing `live_verify.py` endpoint smoke is not a lifecycle/soak runner. |
| M12-R2: Repair configuration and baseline | Generated local configuration and validation record: confirm the actual GPT-OSS and Gemma commands contain the intended RAM cache budget, record runtime/model identities and available RAM/VRAM, and preserve existing operator profiles. | A reviewed dry-run and baseline record precede any model load; the previous default cache risk is not silently carried into copied profiles. No user application is terminated to create headroom. |
| M12-R3: Restart and real console close | Launcher acceptance only: cold start, contextual chat, owned-process shutdown, restart, and model-loaded console close. Capture startup stdout/stderr and verify PID identity plus creation time, not just free ports. | Required services return ready after restart; every owned process is reaped on close; unrelated/reused services survive. Any failure has phase logs and a bounded next hypothesis. |
| M12-R4: Bounded sustained use | One 30-60 minute real local session after restart is reliable. Record request latency, errors, private commit, working set, GPU memory, queue/admission behavior, and shutdown baseline. Define observation intervals and hardware-specific stop/acceptance thresholds before the run. | No crash, persistent backlog, or sustained unexplained resource growth; resource use settles within the recorded baseline/headroom criteria after shutdown. Successful HTTP requests alone do not establish stability. |
| M12-R5: Release the accepted source | Release docs, artifact packaging, and GitHub: classify residual issues, execute installation from the exact candidate, run required CI, record artifact SHA-256 values, then merge/tag through the normal history. | Default local chat has no blocking defect; published source, checks, artifacts, and release notes agree. Preserve `v0.1.0`; do not move published tags. Untested Qwen/cloud paths remain deferred. |

**M12-R1 implementation:** the [public procedure](architecture/LIVE_TESTING.md#prepare-one-reproducible-evidence-record-offline)
and `scripts/m12_acceptance.py` now support offline preparation from a supplied
profile, private phase logs, read-only identity/resource observations, and
separate cleanup results. The targeted fake-only gate passed `34` tests; the
full local offline Python suite passed `254` on 2026-11-03. Windows calls were
validated with fake APIs, not a native process acceptance run. No real model
or service was started during that R1-only task. The subsequent R2 installation
and configuration checks passed. The later operator-directed real pass closed
R3/R4 for the declared host and workload; earlier attempts remain preserved.

The [M12 ledger](validation/M12-RELEASE-SUMMARY.md) remains the evidence source.
The [live testing guide](architecture/LIVE_TESTING.md) describes the existing
harness limits and the acceptance handoff. Do not add new product features to
make a blocked acceptance result appear complete.

### M13: retain useful conversations under user control

Start with export and explicit opt-in local history after M12 is accepted.
Stored conversations are user documents, not model Memory. Keep the existing
API context budget independent from the amount stored on disk or in a browser.

| Task | Scope and owner boundary | Completion evidence |
| --- | --- | --- |
| M13.1: Daily-chat budget review | UI/API conversation contract: measure representative short conversations, Chinese text, and code against the current limits of 12 prior messages, 1536 input budget units, and 256 reply tokens. Specify budget/truncation feedback before considering changes. | Limits and incomplete answers are understandable; any proposed larger budget has measured runtime headroom. Storage never implies sending the entire archive to a model. |
| M13.2: Export the current conversation | Web UI only: export successful visible turns as UTF-8 Markdown and a small versioned JSON format; label incomplete turns if retained. | Exported role order, Unicode, and code text match the displayed conversation; no credentials or hidden provider payloads appear. No export requires a cloud request or a new service. |
| M13.3: Opt-in local retention | Choose one bounded storage adapter after documenting location, quota, retention, deletion, and failure behavior. Page-memory mode remains available; the Core and router remain stateless. Browser storage is one-device/origin storage, not a backup. | Only explicit opt-in survives refresh/restart; users can open, delete, and clear stored conversations. Storage refusal, quota exhaustion, or corrupt data cannot prevent a new chat. No vector database or automatic summary. |
| M13.4: Recovery acceptance | Web behavior and API integration: exercise refresh, selection/reset, deletion, storage failures, and resuming an over-budget saved conversation. | Reopened records never silently exceed `/chat` bounds or resend failed turns; the user can export or start fresh without losing the current draft unexpectedly. |

### M14: incremental replies and truthful stop behavior

The provider contract already exposes `ChatChunk` and streaming, and
`CoreFacade.stream` exists. Reuse those ports; the missing work is the public
API/UI contract, bounded delivery, and verified cancellation/admission behavior.

| Task | Scope and owner boundary | Completion evidence |
| --- | --- | --- |
| M14.1: Streaming contract | Existing Core/provider ports and the API adapter: define bounded events for start, text, completion, error, and cancellation. Preserve non-streaming `/chat`; keep model-specific transport inside providers. | Unsupported providers fail explicitly or use a declared non-streaming mode. Existing clients and route decisions keep their contract. |
| M14.2: Provider execution and admission | Adapter cancellation, timeout, and resource cleanup: decide what each provider can actually stop. Hold the single-operation slot until execution has ended; bound slow-client buffering. | Disconnect/stop/error paths close owned resources without allowing overlapping model work. Where inference cannot be cancelled, UI status says work may continue and the slot remains held. |
| M14.3: Web rendering and recovery | Thin UI: incremental safe text, keyboard-accessible Stop, partial-answer status, and recovery after an interrupted response. | First text appears before completion; partial or failed replies are not silently added as complete history. A new request works after the prior operation actually ends. |
| M14.4: Integrated local acceptance | Targeted offline tests followed by a bounded explicit local check under the shared attempt rule. | Busy, timeout, disconnect, slow consumer, normal completion, and restart behavior remain correct; report time to first text and total latency separately. |

### M15: desktop pet as a status surface

Keep conversation in the Web UI. The first pet integration observes status and
opens that UI; it does not become another model client or lifecycle manager.

| Task | Scope and owner boundary | Completion evidence |
| --- | --- | --- |
| M15.1: Minimal status contract | Extend a provider-neutral API status view only where existing `/live` and `/ready` are insufficient; define offline, starting, ready, busy, and error states without prompts or provider internals. | Status reflects actual execution, including work continuing after a browser timeout. Bounded polling or subscription does not trigger inference. |
| M15.2: Pet adapter | A separate frontend adapter maps those states to visuals and opens the existing chat page. | Losing or closing the pet does not stop Core or models; API loss is visible and recovery works without duplicate launches. |
| M15.3: Integration and packaging | Document connection setup and validate pet/UI use together on the target host. | Pet, browser, and Core show consistent state; neither frontend embeds routing, provider credentials, or model process commands. |

After these milestones, select additional work from actual usage. Vision,
cloud-provider acceptance, voice, cross-session model Memory, Tools, Agents,
and an OpenAI-compatible server remain separate proposals. They do not block
the default local-text release and are not implicitly scheduled here.

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
