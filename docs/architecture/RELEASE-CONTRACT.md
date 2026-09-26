# Oratrice release contract

Status: **M8 contract revision**. This document defines the release vocabulary
and the component scope for the `config/profiles/live.yaml` local-first
profile. It is a decision contract, not evidence that every optional provider
path has been exercised.

## Component scope

The default release scope has four required components (all runtime targets). A
required component must be healthy before the local release can be called ready. The
Core API also serves the bundled `/ui/` surface, which is checked as part of
the M8 product smoke but does not add a fifth process or launcher target.
Optional components are not launch gates unless a release explicitly selects
them.

| Component | Class | Profile identity | Health/readiness contract | Notes |
| --- | --- | --- | --- | --- |
| GPT-OSS | required | target `gpt_oss`; runtime `runtime.gpt_oss`; provider `provider.gpt_oss`; model `model.gpt_oss` | `http://127.0.0.1:8080/health` returns a successful health response | Default local model path |
| Gemma Router | required | target `gemma_router`; runtime `runtime.gemma_router`; provider `provider.gemma_router`; model `model.gemma_router` | `http://127.0.0.1:8090/health` returns a successful health response | Router only; it does not answer user requests |
| LiteLLM Gateway | required | target `litellm_gateway`; runtime `runtime.litellm_gateway`; provider `provider.litellm_gateway` | `http://127.0.0.1:4000/health/liveliness` returns a successful health response | Local gateway for the default routes |
| Core API | required | target `core_api`; runtime `runtime.core_api`; provider `provider.core_api` | `http://127.0.0.1:8000/health` returns HTTP 200 and the JSON liveness/readiness fields are inspected | Uvicorn entrypoint is `oratrice_api.main:app` |
| Bundled Oratrice Web UI | required surface of Core API | route `/ui/`; assets `frontends/web/index.html`, `app.js`, `styles.css` | `http://127.0.0.1:8000/live` is healthy and `/ui/` plus its static assets return HTTP 200 | Same-origin thin client; no separate process, model, provider, or browser-storage contract |
| Qwen-VL | optional | target `qwen_vl`; runtime `runtime.qwen_vl`; provider `provider.qwen_vl`; model `model.qwen_vl` | `http://127.0.0.1:8082/health` when explicitly selected with `--with-qwen` | Direct runtime evidence exists; LiteLLM vision gateway evidence remains deferred |
| DeepSeek | optional cloud | model `model.deepseek_reasoner`; route `route.deepseek_reasoner`; provider `provider.litellm_cloud` | Only an explicit `policy.cloud_opt_in` request with `DEEPSEEK_API_KEY` may select it through the local gateway | Never part of the local-only default |
| OpenWebUI | optional external UI | custom-profile `ui_url`/`ui_health_url` only | A healthy external UI may be opened when explicitly selected in a copied profile | Not installed, configured, or owned by Oratrice |

The required launcher order is `gpt_oss`, `gemma_router`,
`litellm_gateway`, then `core_api`. Qwen-VL is inserted only when selected
and is configured before `litellm_gateway`. The profile's launcher attempt
limit is `3`.

## Component lifecycle states

These states describe an individual target or service. They are deliberately
separate from the release disposition below.

| State | Meaning |
| --- | --- |
| `PLANNED` | The target is present in the resolved plan; no start or health probe has been attempted. |
| `STARTING` | Startup or the health-gated readiness probe is in progress. |
| `READY` | The configured health contract succeeded and the component can serve its scoped contract. |
| `DEGRADED` | The component is usable with a declared non-blocking limitation, or an optional selected component is unavailable. |
| `FAILED` | Startup, configuration, or the health contract failed for the component. A required failure blocks the release. |

`PLANNED` must not be reported as `READY`. A launcher dry-run is therefore
planning evidence only; it starts no process and does not prove model or
gateway readiness.

## Release dispositions

Every release review records exactly one disposition for the declared scope:

| Disposition | Rule |
| --- | --- |
| `PASS` | Every required component is `READY`, and every optional component explicitly selected for this release is `READY`. Unselected optional paths are listed as deferred evidence, not silently treated as tested. |
| `DEGRADED` | Every required component is `READY`, but a selected optional component is `DEGRADED`/`FAILED` or another declared non-blocking limitation remains. The usable scope and limitation must be recorded. |
| `DEFERRED` | The required release evidence, or an explicitly selected component's evidence, was intentionally not attempted or was postponed. No `PASS` claim is made for that scope. |
| `BLOCKED` | A required component is `FAILED`, a required prerequisite is missing (for example a required executable or dependency), or an isolation/security violation prevents a trustworthy result. The release cannot proceed for that scope. |

The default local-only profile can be `PASS` when GPT-OSS, Gemma Router,
LiteLLM, Core API, and the bundled `/ui/` smoke contract are ready; Qwen-VL,
DeepSeek, and OpenWebUI remain optional and their untested paths must be
recorded as `DEFERRED` evidence. Selecting Qwen-VL, cloud DeepSeek, or an
external UI changes the declared scope and requires a new evidence entry.

## Evidence and attempt contract

The offline contract tests read this document and the live profile only. They
must not start a process, open a socket, load model weights, invoke LiteLLM,
or contact a cloud endpoint. Live model/gateway checks are separately
authorized paths.

For each validation path, record:

1. the exact PowerShell command and resolved Python/environment setup;
2. the attempt number (maximum three), collected/passed counts, and relevant
   side-effect sentinels;
3. the component states and one release disposition from the tables above;
4. a failure class (`setup`, `assertion`, or `isolation`) and the changed
   hypothesis when another attempt is justified;
5. for a live launcher run, the final exact scoped ports/processes and whether
   cleanup was automatic or required manual intervention.

After three attempts, or after three consecutive reports of the same root
cause, stop that path. Do not use a fourth run or an unrelated live run to
turn missing evidence into `PASS`.
