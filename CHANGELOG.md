# Changelog

All notable changes to Oratrice are documented in this file. The project
follows [Semantic Versioning](https://semver.org/).

## Unreleased - v0.2 candidate (acceptance blocked)

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

### Validation and release status

- M12-R1 targeted fake-only gate: **34 passed**; full local offline Python
  regression: **254 passed** on 2026-11-03. This did not start services or
  establish real-model or native-process acceptance.
- Pre-R1 local repair regression: **220 Python tests passed**. The earlier
  JavaScript behavior gate passed 11 tests; it was not rerun locally after
  changes confined to launcher/configuration code.
- Clean installation, real local cold start, browser conversation, contextual
  follow-up, busy recovery, and Ctrl+C cleanup passed within their recorded
  scopes. Native window close/restart also passed with lightweight surrogates.
- **v0.2 remains blocked:** real-model restart failed before readiness and
  private commit grew 596.7 MiB during the 30-minute run. Post-repair real-model
  memory, restart, and window-close revalidation were deferred by the operator.
  See the [M12 ledger](docs/validation/M12-RELEASE-SUMMARY.md).

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

