# Oratrice architecture

This file is a compatibility pointer. The normative V1 architecture is in
[`docs/architecture/README.md`](docs/architecture/README.md), with decisions
recorded in:

- [`docs/architecture/ADR-0001-layered-boundaries.md`](docs/architecture/ADR-0001-layered-boundaries.md)
- [`docs/architecture/ADR-0002-v1-migration-and-deprecation.md`](docs/architecture/ADR-0002-v1-migration-and-deprecation.md)

The former statement that `entities/`, `core/`, and the provider interface are
frozen and may not be refactored is **superseded**. Architecture may evolve
when the public contract is preserved or an ADR documents the migration,
rollback, and acceptance checks. The V1 request path is:

```text
frontend -> core facade -> router -> provider manager -> LiteLLM -> local/cloud provider
```

Cloud fallback is opt-in; Agent functionality is outside V1.

