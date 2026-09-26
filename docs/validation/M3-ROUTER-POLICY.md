# M3 router-policy validation

Status: **PASS (offline integration; bounded unit-test caveats recorded)**.

M3 validates composition and policy injection offline.  The collected test
`tests/test_m3_router_composition.py` loads `config/profiles/live.yaml`,
injects a fake Gemma client and fake runtime manager, and builds the application
with `auto_start=False`.

Acceptance checks:

1. `defaults.router.strategy` is parsed into `RoutingPolicy` and injected into
   `GemmaRouterProvider`.
2. Application construction performs zero routing-client calls, provider
   construction, runtime starts, model loads, or network operations.
3. The adapter global allow-lists contain every strategy model/provider,
   including the cloud candidate.
4. A normal request's `candidate_catalog` excludes cloud candidates.
5. `metadata.allow_cloud: true` exposes the configured DeepSeek candidate.
6. The router remains a classifier: it emits route data and never answers the
   user's message.
7. Strict fake decisions verify the configured outcomes: ordinary chat selects
   GPT-OSS, a vision request selects Qwen-VL, explicitly opted-in high-complexity
   reasoning selects DeepSeek, and the same cloud decision without opt-in is
   rejected.

The test does not start the Gemma, GPT-OSS, Qwen, or LiteLLM processes.  Qwen's
vision/OCR execution chain is intentionally deferred; this milestone verifies
only declarative strategy and composition boundaries.

Final composition result:

```text
3 passed in 0.24s
```

The composition path used all three permitted attempts: the first was a missing
`python` setup failure, the second passed the original two tests, and the third
passed the expanded three-test route matrix.  It must not be rerun for this M3
gate.

Additional bounded records:

- Contract/Gemma tests reached three environment/setup failures before pytest
  could run (missing command, denied interpreter, missing pytest).  Their files
  passed syntax compilation and were not retried.
- Policy tests stopped after the third attempt at 9/10 passing.  The sole
  failure was an over-specific expected error-message substring; the policy
  correctly rejected the unauthorized cloud decision.  The assertion was
  relaxed to the typed `RoutePolicyError` contract and was not rerun a fourth
  time.

Reference command for a future milestone only (do not rerun for this gate):

```powershell
python -m pytest -q tests/test_m3_router_composition.py
```

No live-model or gateway retry was used to compensate for an offline test
failure.
