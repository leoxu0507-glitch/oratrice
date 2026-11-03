# Changelog

All notable changes to Oratrice are documented in this file. The project
follows [Semantic Versioning](https://semver.org/).

## [0.3.0] - 2026-11-03

### Release scope

- v0.3.0 includes the M13-M15 conversation, streaming, and status-companion
  work. It adds no vision, cloud-default, voice, Memory, Tool, or Agent behavior.
- M16 local acceptance passed on the recorded Windows host. The immutable
  GitHub tag and release assets are the authority for the exact source, CI run,
  source archive manifest, and checksum. The published v0.2.0 record is
  preserved.

### Added

- M15 versioned `/status` for both frontends: active operation, stopped-stream
  delivery, safe error states, and explicit-only cached readiness. Generation
  tokens prevent late stream callbacks from changing newer operation state.
- Independent loopback-only Tk status pet with a one-click Windows entry,
  keyboard controls, bounded GET polling, offline recovery, and **Open chat**.
  Closing it does not control Core or models. OpenPets 3.2.1 loopback access
  remains unsupported; the operator chose the standalone implementation.
- M14 optional SSE chat through `/chat/stream`, incremental safe text display,
  and keyboard-accessible Stop. Ordinary `/chat` and M13 conversation storage
  remain available. Interrupted turns keep their draft and partial label but
  never enter successful-turn history, saves, or exports.
- Shared chat/route/stream admission through provider execution and cleanup,
  with bounded event buffering, delivery deadlines, and slow-client handling.
  Disconnect/Stop ends delivery while the worker drains upstream output;
  it does not claim to cancel inference.
- Explicit unsupported-stream errors and deterministic provider iterator
  cleanup. SSE adapters reject EOF without a completion marker and use small
  reads to avoid buffering early text behind larger network chunks.
- Web conversation budget feedback using the existing UTF-8/message limits,
  and visible incomplete-reply status when a provider reports `length`.
- UTF-8 Markdown and versioned JSON downloads containing successful visible
  turns and incomplete-reply metadata, without internal provider payloads.
- Explicit opt-in browser history with open/delete/clear controls: at most
  20 conversations, 1 MiB total, and 128 KiB per record. Page-memory mode
  remains the default. Core, Router, and API remain stateless.
- Bounded Web Locks, revision checks, draft protection, and recovery for
  storage refusal, quota errors, malformed data, stale tabs, and archives
  exceeding the unchanged API context budget. New conversation commits its
  reload selection before clearing the visible page.

### Validation

- M16 passed bounded real local GPT-OSS/Gemma/LiteLLM/Core acceptance on
  Windows 11 (build 26200, Python 3.13.5, Tk 8.6, LiteLLM 1.74.3, and
  llama.cpp b9843). Core/Gateway setup, local configuration, and strict Doctor
  passed. Cold readiness was 42.239 s; restart readiness was 37.724 s.
- One 1800.45-second session completed 30 sequential local HTTP requests,
  including 15 codeword question/follow-up pairs, all HTTP 200. Response
  latency was 11.949 s median / 20.637 s maximum. Across 120 resource samples,
  Core tracked memory rose 457.6 MiB overall and 8.4 MiB in the final third;
  the pet rose 1.8 MiB. This met the predeclared 512 / 256 / 32 MiB bounds for
  that run and does not establish leak-free continuous operation. Available
  physical RAM reached 125.7 MiB and was observed without aborting. GPU use
  ranged from 6952 to 7650 MiB.
- Runtime files used for the real03 session matched baseline
  `1e91caf1699b278c4c2a9b4bd39a3f8945f740b9`; the earlier packaging/tests/docs
  candidate was `fa69ab6bfeeae49a578f4276e706637ffbbcf53e`.
- The recorded local model SHA-256 values are GPT-OSS
  `75acd89545d50126692df2116bc3fdf700408b4be1d74d58e8eed13bca028f17` and
  Gemma-3n-E4B
  `ef5c72473575ce0b162c0289f5f3ef983ca99fc2f2272efd5871f6bccc3fb49a`.
- Separate real Edge 156 integration covered five UI workflows and five chat
  requests, including Stop while local generation continued; there were no
  JavaScript runtime errors. First visible text took 15.573 s; the response
  completed in 18.261 s. A sixth native Tk Open chat workflow called Windows'
  default-browser opener successfully; its exact newly opened tab was not
  inspected. The actual web page was exercised separately in Edge through CDP.
- A v0.3.0 archive was extracted into a path containing spaces. On Windows
  PowerShell 5.1.26100.9711, Core/Gateway dependency checks, imports and version
  checks, local configuration, strict Doctor, and launcher dry-run passed. The
  Gateway environment was fresh; the Core environment reused the partial
  environment created by attempt 1, so this was not a zero-state Core install.
- The default launcher smoke reached ready state. The UI and four JavaScript
  assets returned HTTP 200; real local chat returned `PACKAGE_OK` and streaming
  returned `STREAM_OK`. Closing the Tk pet reaped both pet processes while Core
  stayed ready. Closing the launcher console reaped 11 owned identities and
  freed ports 8000, 8080, 8090, and 4000 before the outer guard.
- The setup helper's native-command probe passed: a zero exit with stderr was
  accepted, exit code 7 was preserved, spaced arguments were passed intact,
  and the caller's `ErrorActionPreference` was restored. Seven setup contract
  tests passed after correcting one stale assertion from the first run.
- A 75-file operational comparison matched the release-candidate Git blobs
  except for normal Git line-ending normalization. Core, Router, Provider,
  runtime, and frontend implementation files remained unchanged from baseline
  `1e91caf1699b278c4c2a9b4bd39a3f8945f740b9`; release preparation changed
  setup, packaging, tests, and documentation.
- Ctrl+C cleanup after the cold run and final cleanup after restart reaped all
  owned process identities and freed required ports before outer cleanup.
  Restarted chat returned the expected marker. Closing the pet left Core
  available. After exit, available physical RAM was 10842.0 MiB and GPU use
  was 670 MiB, versus 6824.9 MiB and 912 MiB at the recorded baseline.
- A separate manually overridden 64-token request returned HTTP 200 with an
  empty response. The documented 256-token default completed successfully in
  the subsequent acceptance run. The cause of the low-budget result was not
  established; this record makes no claim about its internal reasoning path.
- The packaging check's first attempt rejected the public `SECRETS.md`
  filename; the corrected second attempt passed. Its focused 27-test gate and
  candidate CI passed on `fa69ab6bfeeae49a578f4276e706637ffbbcf53e`:
  [399 Python and 63 JavaScript tests](https://github.com/leoxu0507-glitch/oratrice/actions/runs/41636332951).
- The first install attempt completed Core dependency installation, but a
  harmless pip stderr notice caused the PowerShell 5 wrapper to report an
  error. The native capture helper was corrected and its zero/nonzero exit,
  stderr, argument quoting, and preference-restoration behavior were verified.
  Attempt 2 completed setup and smoke; it reused attempt 1's partial Core
  environment while creating the Gateway environment fresh.
- M15 local gates passed 86 targeted Python tests, the full 372-test suite,
  compilation, and 63 JavaScript tests. A thousand-failure offline test checks
  backoff without counter overflow. Six actual Tk/Edge/API workflows passed
  with an injected provider: consistent states, stopped-stream draining,
  button URL dispatch, pet/Core independence, and API loss/restart/reconnect.
  Polling triggered no model/provider-health calls. The one-click source
  bundle launched from a path containing spaces and its GUI closed normally
  before outer cleanup. M15 did not repeat real-model or soak acceptance.
- M14 local gates passed 57 targeted Python tests, the full 305-test Python
  suite, Python compilation, and 56 JavaScript tests. Seven actual Edge
  workflows with an injected provider covered streaming, Stop, recovery, and
  M13 persistence integration. Slow send/queue, disconnect, and deadline cases
  passed offline.
- Actual local Gemma/LiteLLM/GPT-OSS acceptance passed: first visible text
  22.973 s, first answer complete 25.000 s, contextual follow-up, Stop/busy/
  recovery, and a completed stream after restart. Cold/restart readiness was
  42.223 / 37.775 s. Both Ctrl+C shutdowns reaped owned identities and freed
  ports before outer cleanup. This bounded pass does not repeat the M12 soak.
- M13's original separate JavaScript gate passed 44 tests; targeted offline
  Python UI/API checks passed 33 tests and the full offline Python suite passed
  276 tests. CI now includes the data and storage modules in its Node gate.
- Actual Edge acceptance passed 12 workflows through the real API/Core with
  an injected deterministic provider, including actual downloads, reload,
  cross-tab events, lock timeout/retry, and failure recovery. Nine UI chat
  requests completed with no browser runtime exceptions. Owned test processes
  were reaped and the test listener closed.
- M13 did not rerun model performance, lifecycle, or sustained-use acceptance.
  The v0.2.0 real-model record remains separate; published tags are unchanged.

M13-M15 are the v0.3.0 feature scope. Their focused development checks and the
integrated M16 local acceptance are recorded separately above.

## [0.2.0] - 2026-11-03

### Added

- M9 lifecycle recovery: retained ownership after incomplete shutdown,
  interrupted-start rollback, Windows child-process supervision, and one
  chat/route admission slot per API instance.
- M10 portable installation: generated local-only configuration, separate Core
  and Gateway environments, strict offline diagnostics, and Windows CI.
- M11 recent conversation: bounded page-local history, legacy single-message
  compatibility, request/context guards, conversation reset, draft recovery,
  busy/error messages, and keyboard behavior.

- M12-R1 reproducible acceptance procedure and opt-in read-only evidence
  collector: offline preparation, phase logs, PID/creation-time tracking,
  resource observations, and distinct automatic/manual cleanup evidence.

### Fixed

- Generated GPT GPU layers default to `auto` instead of forcing `999`; explicit
  non-negative counts remain supported. Compatible llama.cpp builds can fit
  available VRAM rather than being blocked by an explicit full-offload value.

- Acceptance listener checks read Windows TCP tables, avoiding false unknown
  results when closed loopback connections time out. API read failures remain
  unknown rather than being treated as free ports.

- M12 readiness uses the lightweight Core `/live` probe, avoiding expensive
  provider health calls during periodic UI status polling.
- GPT-OSS and Gemma explicitly disable extra RAM-backed prompt caches by
  default. `--prompt-cache-mib` accepts a finite non-negative per-model budget;
  existing operator profiles require an explicit update.
- Startup failure summaries preserve typed runtime state and exit codes,
  including zero, without echoing exception payloads or credentials.

### Validation

- Fresh Core/Gateway installation, strict Doctor, generated local-only profile,
  and dry-run passed. The code gate passed 276 Python and 11 JavaScript tests;
  exact release checks are linked from the release and PR.
- Real cold start (40.70 s), contextual chat, nine browser checks, Ctrl+C cleanup,
  restart (37.68 s), and model-loaded classic-console close passed.
- The 1800-second session completed 24 sequential question/follow-up pairs.
  All 51 controller chat requests returned HTTP 200; median latency was
  15.496 seconds and maximum 20.033 seconds. The browser also exercised one
  intentional busy rejection and recovered successfully.
- Total tracked private commit grew 56.1 MiB; the final 13 samples grew
  19.4 MiB within the recorded bounds. All observed owned processes exited
  and required listeners were free before emergency finalization.
- The operator revised the earlier physical-free-RAM abort policy before this
  pass. Low Windows available-RAM counters were observed without aborting;
  earlier guarded stops and unaccepted runs are retained in the
  [M12 ledger](docs/validation/M12-RELEASE-SUMMARY.md).

### Known limits

- The real-use result covers the recorded Windows host, b9843 runtime, local
  models, small context, and sequential 30-minute workload. Long contexts,
  high concurrency, continuous uptime, Qwen-VL, and cloud inference are not
  accepted by this release.
- History is page-local and bounded; there is no persistence, streaming,
  automatic summary, voice, Memory, Tools, or Agent behavior.

## [0.1.0] - 2026-09-27

### Added

- Provider-neutral Core facade, typed registry, resource manager, and runtime
  lifecycle management.
- Gemma routing boundary with declarative task and capability matching.
- LiteLLM gateway integration for local and opt-in cloud providers.
- FastAPI endpoints for chat, routing, liveness, readiness, and health.
- Windows one-click launcher with health-gated startup and process ownership.
- Thin same-origin Web UI served by the Core API.
- Offline test suite, environment doctor, release validation, and M1-M8
  architecture/operations documentation.

### Known limitations

- The validated live profile assumes the maintainer's local `D:\AI` runtime
  layout; other installations must copy and adjust the profile.
- Qwen-VL and DeepSeek are optional and disabled by default.
- The required M8 live path passes, while the overall V0.1 status remains
  degraded because launcher cleanup could not be conclusively verified under
  the Codex ConPTY harness and local GPU headroom is limited.

[0.1.0]: https://github.com/leoxu0507-glitch/oratrice/releases/tag/v0.1.0

[0.2.0]: https://github.com/leoxu0507-glitch/oratrice/releases/tag/v0.2.0
