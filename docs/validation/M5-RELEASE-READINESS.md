# M5 Release Readiness

M5 is a single, offline release gate.  It does not repeat the M1--M4 test
paths and it must never start a model, gateway, subprocess, socket, or cloud
request.

## Gate and attempt policy

The gate is `tests/test_m5_release_gate.py`.  The path has a maximum of three
attempts.  Each attempt records the command, Python/PYTHONPATH setup, collected
and passed counts, failure class (`setup`, `assertion`, or `isolation`), and
socket/process/model/credential side-effect counters.  Three attempts or
three consecutive reports of the same root cause stop the gate; no fourth
attempt or fallback live run is allowed.

Recommended invocation (from `D:\AI\projects\Oratrice`):

```powershell
$env:PYTHONPATH = "D:\AI\infrastructure\litellm\.venv\Lib\site-packages;D:\AI\projects\Oratrice\work\oratrice-test-venv\Lib\site-packages"
$env:PYTHONDONTWRITEBYTECODE = "1"
python -B -m pytest -q -p no:cacheprovider tests/test_m5_release_gate.py
```

### Attempt ledger

| Attempt | Result | Classification | Notes |
| --- | --- | --- | --- |
| 1 | 3 passed, 2 failed | gate instrumentation | AST parser rejected a harmless UTF-8 BOM in `router/policy.py`; the socket sentinel was installed before TestClient's Windows self-pipe. No model, provider, or external network call occurred. |
| 2 | terminated | gate instrumentation/isolation guard | Replacing `socket.socket` after portal creation still interfered with AnyIO and was stopped; no service or model was started. |
| 3 (final) | **5 passed in 0.59s** | PASS | BOM-safe AST parsing and `socket.create_connection` sentinel; all checks completed in-process. No socket connection, subprocess, model construction, gateway call, or cloud credential request was observed. |

The three-attempt limit is exhausted for this path. Do not rerun this file in
this release review; subsequent changes require a new, explicitly tracked gate
path.

## Coverage

The gate checks:

1. AST import boundaries and the `oratrice_api.main:app` Uvicorn entrypoint.
   The entrypoint only registers the API; Application construction remains in
   FastAPI lifespan.
2. Live-profile IDs, router strategy candidates, provider references,
   cloud-opt-in priority, launcher order, Core API health URL/timeout, Qwen's
   optional ordering, attempt limit, and secret omission from `to_dict()`.
3. Model/gateway alias resolution to canonical runtime IDs without starting a
   process.
4. `--profile` propagation to the launcher/API environment and restoration of
   both an injected mapping and the process environment in `finally`.
5. In-process `/chat`, `/route`, and `/health` contracts with an injected fake
   facade.  An empty/unknown component graph is reported as healthy liveness;
   an active unhealthy component remains unhealthy while HTTP stays 200.
   Router transport failures map to 503, ordinary route policy/validation
   failures remain 422, and validation/error envelopes never echo input,
   prompts, causes, or raw provider data.
6. Socket and subprocess sentinels.  Any attempted network/process/model
   side effect fails the gate immediately.

## Historical evidence and limits

The repository currently contains 26 `test_*.py` files and 96 statically
defined test functions.  The latter is an inventory number, not a pass count;
parameterized expansions and historical runs must not be presented as a
current full-suite green result.

Reported targeted results are: M1-09 optional DeepSeek configuration 3
passed (the historical full suite then reported 64 passed); M2 launch plan,
orchestrator, and CLI 4, 10, and 4 passed; M3 composition 3 passed; M4 API 13
passed; and M4 launcher/API 3 passed.  M4's final run was the third permitted
attempt; subsequent static fixes were not rerun on that old path.

## Deferred or blocked evidence

- Direct Qwen-VL runtime/mmproj validation passed, but the LiteLLM-to-Qwen
  multimodal gateway chain remains deferred after readiness-harness failures.
  No gateway vision pass is claimed.
- DeepSeek cloud inference is blocked/skipped without `DEEPSEEK_API_KEY`.
  Local gateway configuration and secret wiring are the only accepted proof.
- An initial full live-chain readiness attempt timed out; the later product
  chain reported `core_chain_pass=True`, while supervisor exit/model-alias
  mismatch fields were non-authoritative diagnostics.
- M3 policy assertions were relaxed after the third attempt and were not run a
  fourth time.  Contract/Gemma setup failures likewise remain historical
  evidence, not live retries.

The M5 gate is therefore a release-readiness boundary and isolation proof, not
a claim that every deferred provider path is live or that the entire historical
suite is green.

## Launcher dry-run

After the offline gate, the packaged Windows entrypoint was checked separately
with `Start-Oratrice.exe --dry-run --no-browser`. The first sandboxed attempt
could not create the configured Python process because access to the base
Python installation was denied by the sandbox. The second attempt, outside
that sandbox and still in dry-run mode, passed and reported exactly four
planned targets in order: `gpt_oss`, `gemma_router`, `litellm_gateway`, and
`core_api`; the UI was `NOT_REQUESTED`. No model, API server, gateway, browser,
or listening socket was started.
