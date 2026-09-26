# V1 migration runbook

Migration is additive and reversible.  Follow the stages in
[`ADR-0002-v1-migration-and-deprecation.md`](ADR-0002-v1-migration-and-deprecation.md)
and keep the offline suite green at each gate.

## Before changing a frontend

1. Keep the existing model/runtime IDs and legacy YAML entries.
2. Add provider and route sections with local-first policy; cloud fallback must
   be an explicit configuration value.
3. Run `python -m pytest -q` (or `py -m pytest -q`) with no model process.
4. Confirm `tests/test_import_boundaries.py` finds no frontend-to-provider edge.

## Moving callers

Construct the application at the composition root and pass the facade to each
frontend:

```python
from core.application import build_application

application = build_application("config/oratrice.yaml", auto_start=False)
reply = application.facade.chat("model.local", "hello")
```

The `AIService` object remains a compatibility shim for one migration window;
its direct constructor emits `DeprecationWarning`.  Keep old `chat` and
`stream` argument meaning while callers move.

## Adapter and rollback gate

Introduce the LiteLLM-backed adapter behind the provider port only after fake
adapter tests cover success, streaming, timeout, unavailable provider, and
credential redaction.  During the transition, retain the direct local adapter
as a composition/configuration switch.  If a gate fails, switch the
composition root back to the known local adapter without changing frontend
code or reverting unrelated registry/entity work.

## Retiring compatibility surfaces

Remove a legacy surface only when all of the following are recorded:

- the offline contract suite and import-lint checks pass in CI;
- a repository-wide call-site search finds no production use of the old name;
- release notes document the replacement and rollback path; and
- a previous local route can be restored by tested configuration rollback.

Retirement that changes a public API or configuration field requires a new
ADR.  Never log credentials or full user messages solely to support migration
diagnostics.
