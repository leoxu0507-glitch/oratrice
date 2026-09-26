# ADR-0002: V1 migration and deprecation policy

- **Status:** Accepted migration plan
- **Date:** 2026-08-03
- **Related:** ADR-0001

## Context

The current code path is approximately:

```text
cli.py -> AIService -> ResourceManager -> RuntimeLauncher
                         \-> LlamaCppProvider -> llama-server HTTP API
```

It must move to the layered path without breaking existing resource IDs or
the basic `chat`/`stream` behavior. The target project is local-first, so a
provider migration must not silently send data to a cloud service.

## Decision

Use compatibility wrappers and additive configuration first. Do not perform a
flag-day rewrite. The following mapping is the V1 migration contract:

| Current surface | V1 target | Compatibility rule |
| --- | --- | --- |
| `core.ai_service.AIService` | `core.facade.CoreFacade` | Keep `AIService` as a thin delegating shim for one V1 compatibility window; emit `DeprecationWarning` when constructed directly. Preserve `chat` and `stream` argument meaning. |
| `core.manager.ResourceManager` model/runtime methods | provider-manager lifecycle port plus a resource registry facade | Keep `start_model`, `stop_model`, and `status_model` until all frontends use the new port. Do not remove runtime process handling while a local provider still needs it. |
| `providers.base.BaseProvider` | provider port used by the provider manager | Treat the existing methods as an adapter-compatible subset. Add new methods only through a versioned port or defaulted capability, not by breaking existing providers. |
| `providers.llama_cpp.LlamaCppProvider` | LiteLLM-backed local adapter (with a temporary direct adapter) | Preserve the local endpoint and model ID mapping. The direct adapter is compatibility-only and is not imported by frontends. |
| direct construction in `cli.py` | composition-root factory | Move wiring first; keep CLI input/output behavior unchanged. |
| `config/resources.yaml` runtime/model entries | additive `providers` and `routes` entries | Existing `runtime`, `path`, `enabled`, and resource IDs remain valid. Missing new fields use local-only legacy defaults. |

## Migration stages and gates

### Stage 0 — document and observe

- Land ADR-0001 and this plan.
- Add import-boundary and contract tests before moving implementations.
- Record current CLI, `chat`, `stream`, runtime-start, and error behavior as
  compatibility expectations.

**Gate:** tests describe current behavior and can run with a fake provider.

### Stage 1 — introduce ports behind the current service

- Add facade/router/provider-manager ports and a composition-root factory.
- Wrap the existing registry, runtime manager, and llama.cpp provider.
- Route the default model to the existing local endpoint; no cloud fallback
  unless explicitly configured.

**Gate:** the existing CLI passes through the facade while the old constructor
  remains available as a shim.

### Stage 2 — make LiteLLM the target adapter

- Add the LiteLLM adapter behind the provider-manager port.
- Normalize non-streaming, streaming, timeout, and provider errors.
- Keep direct llama.cpp only as a rollback/compatibility implementation.

**Gate:** adapter contract tests pass; a local smoke test and an offline fake
  test both pass; no frontend imports LiteLLM or a provider module.

### Stage 3 — migrate frontends and configuration

- Change CLI/desktop/web callers to the facade factory.
- Add provider/route entries to configuration, retaining old entries and IDs.
- Enable explicit local-first/fallback policy and document secret handling.

**Gate:** all production frontend call sites use the facade; a search or AST
  check finds no direct provider construction outside the composition root or
  compatibility tests.

### Stage 4 — retire compatibility surfaces

Remove a shim only after all of these are true:

1. The V1 migration gates above pass in CI.
2. A repository-wide call-site search finds no production use of the old
   surface.
3. Release notes contain the replacement API and rollback instructions.
4. The next release has a tested configuration rollback to the previous local
   route.

Removal is a separate change/ADR if it changes a public API or config field.

## Deprecation and rollback rules

- Deprecations are additive and observable: issue `DeprecationWarning`, name
  the replacement, and point to this ADR. Do not silently change routing.
- Keep legacy config parsing read-only and local-only by default. A missing
  provider/route section must not enable cloud traffic.
- Keep a feature/config switch for the target adapter during Stage 2–3 so a
  provider outage can fall back to the direct local adapter without changing
  frontend code. The switch belongs in composition/config, not in the router's
  business policy.
- Never log or persist provider credentials or full message content merely to
  support migration diagnostics.
- If a migration gate fails, retain the wrapper and revert the composition
  root to the known local adapter; do not revert unrelated entity/config work.

## V1 acceptance boundary

V1 is complete when the request path has one facade, deterministic local-first
routing, provider-manager health/readiness, LiteLLM normalization, stable
streaming/error contracts, and compatibility coverage for existing model IDs.
Agent planning/tool execution, memory, desktop orchestration, and other
features remain outside this ADR and require separate scope/ADRs.

