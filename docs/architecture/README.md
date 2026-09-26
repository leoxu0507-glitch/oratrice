# Oratrice architecture baseline (V1)

**Status:** V1 target baseline (2026-08-03)  
**Scope:** request routing and provider integration only  
**Supersedes:** the "V1 freeze" language in the root `architecture.md`

This document is the normative map for the local-first AI path. It describes
boundaries and contracts; it does not add Agent functionality. The existing
runtime/resource implementation remains a compatibility implementation while
the path below is introduced incrementally.

## 1. Target request path

```text
frontend (CLI / desktop / web)
        |
        v
core facade (stable public API and request/response contracts)
        |
        v
router (model, policy, and fallback decision)
        |
        v
provider manager (availability, lifecycle, health, and capability lookup)
        |
        v
LiteLLM adapter (one normalized invocation boundary)
        |
        +--> local provider (llama.cpp, Ollama, ...)
        +--> cloud provider (only when policy/configuration permits)
```

The composition root (`main.py` initially, then a dedicated bootstrap module)
creates concrete objects and injects them into the facade. No frontend may
construct a provider or call LiteLLM directly.

### 1.1 Responsibilities

| Layer | Owns | Must not own |
| --- | --- | --- |
| Frontend | User interaction, presentation, cancellation, and conversion to/from the public facade contract | Provider URLs, SDK calls, route selection, process management |
| Core facade | Stable `chat`/`stream` (or equivalent) API, validation, correlation IDs, and public errors | HTTP/SDK/process details or provider-specific branching |
| Router | Deterministic model/provider selection, local-first policy, explicit fallback policy | Network calls, process startup, UI concerns, response parsing |
| Provider manager | Provider registration, lifecycle/start readiness, health, capabilities, and retry/timeout policy | Choosing a business route or formatting frontend output |
| LiteLLM adapter | Mapping the internal request to LiteLLM and normalizing responses/errors/streams | Reading UI state or mutating resource registry data |
| Local/cloud adapters | Provider-specific credentials, endpoints, and quirks behind the adapter/manager port | Being imported by frontends or the router |
| Entities/contracts | Plain data and protocol types (`ModelRef`, `RouteDecision`, `ChatRequest`, `ChatChunk`, `ProviderHealth`) | I/O, subprocesses, SDK imports, global state |
| Config/registry | Loading and validating YAML/resource metadata | Calling providers or making runtime decisions |

The current `core.ai_service.AIService`, `core.manager.ResourceManager`, and
`providers.llama_cpp.LlamaCppProvider` are treated as compatibility
implementations of these responsibilities. The migration ADR defines when
each is wrapped, renamed, and eventually retired.

## 2. Dependency rules

Dependencies point toward contracts and orchestration, never toward a
concrete transport. The following rules are normative and can be checked by
an import-lint test (for example, an AST walk over production modules).

1. **Frontends depend only on the core facade and public contracts.** A
   frontend may import a composition-root factory, but it must not import
   `providers.*`, `litellm`, `requests`, cloud SDKs, or `subprocess`.
2. **The facade depends on ports/contracts, entities, and the router port.**
   It must not import a concrete provider adapter, LiteLLM, HTTP clients, or
   process APIs.
3. **The router depends on route policy, entities, configuration abstractions,
   and a provider-manager port.** It does not perform health checks, network
   calls, or process startup. A route decision is data, not an invocation.
4. **The provider manager depends on provider ports and lifecycle abstractions.**
   It may call a provider adapter and a runtime controller, but it must not
   import frontends or decide user-facing fallback semantics.
5. **Only the LiteLLM adapter imports `litellm`.** Provider-specific SDKs and
   HTTP clients are confined to `providers/` adapters. A direct provider
   adapter is a temporary compatibility path, not a frontend dependency.
6. **`entities/` is dependency-light and side-effect free.** Entities may use
   the Python standard library only; they must not import `core`, `providers`,
   `config`, or external SDKs.
7. **`config/` contains data, not executable policy.** YAML is parsed by the
   registry/bootstrap layer. A config entry may select a route or provider,
   but cannot cause an import or network call by itself.
8. **The composition root is the only concrete wiring point.** It is the
   allowed place to choose the registry, router implementation, provider
   manager, LiteLLM adapter, and compatibility shims.
9. **Tests follow production direction.** Unit tests may use fakes at a port;
   they must not make network/process calls by default. Integration tests that
   exercise a local runtime are explicitly marked and opt-in.
10. **No Agent layer is implied.** Agent planning, tool use, memory, and
    autonomous loops are outside V1 and must not be added as hidden behavior
    to the facade, router, or provider manager.

### 2.1 Import-boundary acceptance checks

The baseline is accepted when all of the following are true:

- An import-lint check finds no forbidden production edge from rules 1–7.
- A fake provider can be injected at the provider-manager port and exercised
  through the facade without importing LiteLLM or making a network call.
- Given the same model and policy inputs, the router returns the same
  `RouteDecision`; route selection is not delegated to a provider SDK.
- A provider failure is surfaced as a stable core error with a correlation ID;
  transport-specific exceptions do not cross the facade boundary.
- The default policy is local-first. Cloud fallback is disabled unless an
  explicit route/policy setting enables it; no credential is read merely by
  loading `resources.yaml`.
- Streaming and non-streaming calls use the same route decision and provider
  identity, and cancellation/timeout behavior is testable at the facade port.
- Existing V1 CLI behavior can be run through the compatibility shim while
  the new path is enabled (see ADR-0002).

## 3. Contract and configuration boundaries

The public facade contract should carry a model identifier, message(s),
generation options, and optional request metadata. It returns a response or a
stream of chunks plus normalized usage/finish information. The contract must
not expose a `requests.Response`, LiteLLM object, subprocess handle, or
provider-specific error class.

Resource IDs in `config/resources.yaml` remain the source of model/runtime
identity during V1. New provider/route fields are additive. Existing
`runtime`, `path`, `enabled`, and model IDs continue to load unchanged while
the router/manager are introduced. A config migration may add, for example:

```yaml
providers:
  local_llama:
    kind: local
    driver: litellm
    model: gpt-oss
    base_url: http://127.0.0.1:8080/v1

routes:
  model.gpt_oss:
    provider: local_llama
    fallback: []
```

The exact schema is owned by the configuration/registry work. This example
sets the boundary only: route data is declarative, and secrets belong in the
runtime environment/secret store rather than committed YAML.

## 4. Refactoring policy

The old root `architecture.md` said that `entities/`, most of `core/`, and
the provider base interface were frozen and that no architectural refactor
was allowed. That position is **withdrawn**. Refactoring is allowed when it
preserves the public facade contract or includes an ADR and a migration path.
Small, reversible changes may proceed without a new ADR; a change needs an
ADR when it changes a layer boundary, public contract, configuration schema,
provider selection semantics, or data/privacy behavior.

An ADR must state the context, decision, dependency impact, migration and
rollback plan, and acceptance checks. Architecture is therefore a maintained
baseline, not a permanent freeze.

## 5. V1 non-goals and open decisions

V1 does not define Agent planning/tool execution, long-term memory, desktop
window orchestration, multi-user auth, billing, or a cloud-first policy.

The following remain explicit follow-ups rather than hidden assumptions:

- the supported LiteLLM version and exact adapter API;
- the final provider/route YAML schema and secret-resolution mechanism;
- whether runtime process control stays in `ResourceManager` or moves behind
  the provider-manager lifecycle port;
- the stable public names for the facade request/response types.

## 6. Test and migration references

The acceptance checks above are exercised by the offline contract suite.  The
test matrix, fake seams, standard commands, and explicit local-model smoke
procedure are maintained in [`TESTING.md`](TESTING.md).  The staged caller
migration, adapter rollback gate, and compatibility-shim retirement checklist
are maintained in [`MIGRATION.md`](MIGRATION.md) and ADR-0002.
