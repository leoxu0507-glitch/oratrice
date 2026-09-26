# M8 / V0.1 release summary

- Date: 2026-08-22 (Asia/Hong_Kong)
- Canonical checkout: `D:\AI\projects\Oratrice`
- Version scope: M8 thin Web UI and release hardening
- Required functional chain: **PASS**
- Functional regression baseline: **PASS** (`150 passed`, Attempt 2)
- Final offline release gate: **DEGRADED** (post-limit docs fix not rerun)
- Overall V0.1 disposition: **DEGRADED**

M8 turns the previously verified local Core chain into a directly usable local
product surface without adding Agent behavior. The default launcher now starts
the existing required stack and opens the bundled same-origin page at
`http://127.0.0.1:8000/ui/` after `/live` succeeds. OpenWebUI remains an
optional external UI selected only through a copied profile; Oratrice does not
install, configure, or own it.

## M8 ledger

| Work item | Result | Evidence |
| --- | --- | --- |
| M8-00A LiteLLM logging privacy | PASS | Focused `13 passed`; `set_verbose: false`, `turn_off_message_logging: true`, `log_raw_request_response: false`, and redaction settings are configured; live target receives `LITELLM_LOG=WARNING` from profile |
| M8 public model alias | PASS | Delegated focused `7 passed`; public `ChatResponse`/`ChatChunk.model` preserves the request alias while internal transport data stays provider-local |
| M8 bundled Web UI | PASS | UI hosting focused `2 passed`; `/ui/`, `app.js`, and `styles.css` are served without constructing the Application; the browser client uses only same-origin `/live`, `/ready`, `/chat` |
| M8 launcher UI contract | PASS | `13 passed` on Attempt 2; live profile defaults to `ui_url=http://127.0.0.1:8000/ui/` and `ui_health_url=http://127.0.0.1:8000/live` |
| M8 offline regression | DEGRADED final gate | Attempt 1 reached `149/150`; after the boundary fix, Attempt 2 passed `150 tests in 2.08s`; final Attempt 3 reached `149 passed / 1 failed` because the release-contract document dropped the historical phrase `four required components`. The phrase was restored, but the three-attempt limit forbids a fourth run |
| M8 live feature path | PASS | `/ui/` 200, JS 200, `/ready` 200 for four required targets, `/route` 200 with `gpt_oss/provider.litellm_gateway`, `/chat` 200 with `gpt_oss` and visible `M8_OK` |
| Launcher cleanup investigation | DEGRADED evidence | Codex ConPTY Ctrl+C closed listeners but did not reap owned processes; managed and native handler harnesses both failed, exact-PID cleanup succeeded, and handler changes were reverted. Original Job Object source restored; rebuilt 8704-byte EXE SHA-256 is recorded in [M8-08](M8-08-REAL-CHAIN.md); dry-run PASS |

## Architecture impact

```text
OpenPets/CLI/other frontend
          |
          v
  bundled Oratrice Web UI (/ui/) ──> Core API (/live,/ready,/chat,/route)
                                      |
                                      v
                                  CoreFacade
                                      |
                                      v
                                  Gemma Router
                                      |
                                      v
                           Provider / LiteLLM Gateway
                                      |
                                      v
                                  GPT-OSS local
```

The UI is static HTML/CSS/ES module code under `frontends/web/`; it adds no
Node runtime, build step, process, port, browser storage, or provider SDK. The
Core API serves the assets from the same origin. The launcher remains the only
process orchestration boundary. Provider response models now expose the public
request alias rather than an internal filesystem/path-like transport model.

LiteLLM payload logging is configured as metadata-only. The profile supplies a
non-secret log level to the gateway process, and the gateway config disables
raw request/response and message logging while enabling message and API-key
redaction. Credentials remain environment-backed and are not stored in the
repository or UI.

## What is done

- A user can launch the local required stack and open the bundled Oratrice UI.
- The UI can display service status and send a normal local text message.
- `/live`, `/ready`, `/route`, and `/chat` retain their provider-neutral API
  contracts.
- Public model aliases no longer expose internal transport paths.
- The M8 functional baseline is green at `150 passed` on Attempt 2. The final
  offline gate remains **DEGRADED** because the obvious Attempt 3 documentation
  compatibility fix was not rerun after reaching the three-attempt limit.
- Qwen, cloud, browser automation, and external OpenWebUI were not needed for
  the default local product path.

## What remains

- Do not retry the exhausted cleanup path in M8. The next milestone should
  redesign external lifecycle supervision, or validate the original Job Object
  path in a real user console before altering launcher code. Do not infer
  process reaping from listener closure, dry-run, or final port state.
- Keep the release disposition **DEGRADED** until a separately authorized
  lifecycle design has trustworthy process-reaping evidence and hardware
  headroom is reassessed. M7/M8 observed only about 418 MB free RAM and 107 MiB
  free VRAM at peak; high concurrency, long context, continuous uptime, and
  simultaneous Qwen remain unverified.
- Keep Qwen-VL through LiteLLM and DeepSeek cloud explicitly deferred. They are
  configuration candidates, not accepted V0.1 live capabilities.
- Future desktop-pet integration should consume status/notifications and reuse
  the Core API; it should not copy chat, routing, or provider logic into the
  pet process.

M8 does not implement Memory, Tools, Agents, voice, vision, cloud fallback, or
streaming. Those remain later scope and must not be smuggled into the thin UI
or Core release contract.
