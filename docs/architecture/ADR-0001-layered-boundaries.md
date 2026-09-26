# ADR-0001: Establish layered request and provider boundaries

- **Status:** Accepted V1 baseline
- **Date:** 2026-08-03
- **Scope:** frontend-to-provider request path
- **Supersedes:** the freeze statement in root `architecture.md`

## Context

The current implementation has a useful resource registry, runtime launcher,
`AIService`, and llama.cpp provider, but the CLI constructs concrete providers
and the service knows about runtime management. The next target is a
local-first path that can select local or cloud providers through LiteLLM
without making every frontend aware of transport details. A permanent
"do not refactor" rule would prevent that migration and has already become a
source of ambiguity.

## Decision

Adopt the following dependency direction:

```text
frontend -> core facade -> router -> provider manager
                                      -> LiteLLM adapter -> provider
```

The facade, router, and provider manager communicate through ports/contracts.
The composition root wires concrete implementations. LiteLLM is the sole
normalization boundary for provider calls in the target path; local/cloud
drivers remain infrastructure details. Entities remain side-effect-free data
objects. Configuration is declarative and is parsed by registry/bootstrap
code.

The router owns *which* provider should be used. The provider manager owns
*whether/how* that provider is available (health, readiness, lifecycle, and
capabilities). The adapter owns *how* a normalized request is encoded for
LiteLLM and how transport errors become core errors. A local-first policy is
the default; cloud fallback requires explicit configuration.

The previous freeze language is revoked. Refactoring `entities/`, `core/`, or
provider interfaces is permitted when the public contract is preserved or an
ADR records the break, migration, rollback, and acceptance checks.

## Consequences

Positive:

- A CLI, desktop UI, and future web frontend share one stable facade.
- Routing policy can be tested with pure inputs, without network/process work.
- Provider replacement and LiteLLM upgrades stay inside infrastructure
  adapters.
- Local-first/privacy behavior is explicit and auditable.

Costs and risks:

- Additional ports and wiring are introduced during migration.
- Runtime lifecycle and model-loading behavior must be separated carefully
  from request routing.
- The LiteLLM adapter becomes a critical compatibility boundary and needs
  contract tests against fake and real local providers.

## Acceptance checks

1. An import-lint test enforces the dependency rules in
   `docs/architecture/README.md`.
2. A fake provider-manager implementation can serve `chat` and `stream`
   through the facade with no network, subprocess, or LiteLLM import.
3. Router tests cover explicit provider selection, local-first default,
   disabled fallback, enabled fallback, and no-route errors.
4. Adapter tests normalize a successful response, a stream, timeout, and
   provider error into stable core-level results/errors.
5. The compatibility CLI still runs during the migration gate, and no Agent
   behavior is present in the request path.

## Alternatives considered

- **Keep the CLI-to-provider wiring:** rejected; it duplicates policy and
  prevents other frontends from sharing behavior.
- **Let the router call LiteLLM directly:** rejected; route selection and
  transport/lifecycle concerns become inseparable and hard to test.
- **Freeze existing modules indefinitely:** rejected; it conflicts with the
  required facade/router/provider-manager migration and blocks safe evolution.

