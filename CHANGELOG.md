# Changelog

All notable changes to Oratrice are documented in this file. The project
follows [Semantic Versioning](https://semver.org/).

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
