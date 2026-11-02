# Changelog

All notable changes to Oratrice are documented in this file. The project
follows [Semantic Versioning](https://semver.org/).

## Unreleased — v0.2 candidate (acceptance blocked)

- M12: Core readiness uses the lightweight `/live` process probe, avoiding
  active-provider inference checks during periodic UI readiness polling.

- M9: truthful runtime shutdown, interrupted-start rollback, Windows process
  supervision, and one chat/route admission slot per API instance.
- M10: generated local configuration, isolated Gateway installation, strict
  offline diagnostics, and a portable full-suite CI definition. The recorded
  clean-checkout install and 180-test offline regression passed; remote CI was
  not dispatched in the M10 validation.
- M11: bounded recent conversation in the Web UI, legacy single-message
  compatibility, request-size guards, reset, recoverable UI errors, and
  keyboard behavior checks. There is no persistent history or streaming.
- v0.2 is blocked: real restart did not reach readiness, model-process private
  memory rose during the 30-minute run, and window-close acceptance is deferred.

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

