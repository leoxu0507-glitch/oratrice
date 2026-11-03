# V1 testing and isolation guide

The ordinary Python suite is an offline contract suite: it should run without
model weights, a running local runtime, live provider requests, or cloud
credentials. It verifies application boundaries without turning the test
runner into a service orchestration tool.

## Standard commands

Use the repository's existing `.venv` when available. CI's Python baseline is
3.13; record the actual interpreter version in local results. Create the
environment only if it is missing, and install dependencies only when needed:

```powershell
# One-time setup, only if .venv is missing.
py -3.13 -m venv .venv
# Run only when dependencies need to be installed or updated.
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt -c constraints.txt
```

From the repository root, run pytest with a fresh child directory below an
existing writable temporary parent. Pytest may clear the `--basetemp`
directory, so use a new child for each run and never reuse a directory with
unrelated contents:

```powershell
$pytestTempParent = Join-Path (Get-Location) 'work\pytest-basetemp'
New-Item -ItemType Directory -Force -Path $pytestTempParent | Out-Null
$pytestBaseTemp = Join-Path $pytestTempParent ([guid]::NewGuid().ToString('N'))
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp $pytestBaseTemp
```

The Node behavior suite is an independent gate:

```powershell
node --test tests/web_chat.test.cjs
```

CI uses Python 3.13 and Node 22, compiles the Python sources, then runs
pytest and the Node gate. Record the actual local Python and Node versions
when reporting results.

M11's separate JavaScript gate uses Node's built-in test runner and VM with
inert DOM, fetch, and timer fakes. Node is test tooling only; no frontend build
or npm package is required. CI selects Node 22; local evidence records the
version actually used. The Python suite checks the shared UI/API contract but
does not spawn Node. The JS gate exercises the shipped source's conversation
and recovery behavior; it does not substitute for an actual browser or model.

## Isolation rules

- Provider and gateway tests inject a requests-compatible fake session.
- Runtime tests inject process runners, readiness probes, and sleepers.
- Router-model tests inject a fake client that returns a fixed JSON decision.
- Facade tests inject a provider registry and assert normalized responses,
  streams, errors, provider identity, and request correlation IDs.
- Import-boundary tests inspect ASTs and do not import a transport SDK.
- `tests/manual_chat_smoke.py` is deliberately not named `test_*.py`; it is a
  manual request to an OpenAI-compatible server that an operator has already
  started. `scripts/live_verify.py --live` is a separate explicit HTTP check
  for configured, already-running endpoints; it does not start a runtime.

Adding a test that opens a socket, starts a subprocess, loads model weights,
or reads a cloud secret by default is a contract violation.  Put such a check
behind an explicit manual command and document its prerequisites.

## Live HTTP checks and launcher acceptance

`tests/live/` is excluded from ordinary pytest. As described in
[`tests/live/README.md`](../../tests/live/README.md),
`scripts/live_verify.py --help`, `--dry-run`, and `--fake` are offline checks;
only the explicit `--live` mode sends HTTP requests. It checks an endpoint
that is already running and never starts or stops a model process. Its chat
check targets the configured provider-compatible `/v1/chat/completions`
endpoint; it does not exercise Oratrice's application `/chat` route or bundled
UI. Cloud checks also require `--allow-cloud`.

A successful fake check does not exercise an endpoint. A successful HTTP
smoke only shows that the configured endpoint answered that request; neither
proves launcher cleanup or long-term stability. Real startup and shutdown
acceptance is a separate launcher check on the intended Windows host. Observe
listener closure and process reaping separately: a closed port alone does not
show that the launcher-owned process exited.

## Contract matrix

| Contract | Tests | Isolation seam |
| --- | --- | --- |
| Entity/registry identity and metadata | `test_registry.py` | Temporary YAML |
| Config references and secret policy | `test_config_loader.py` | Temporary YAML + `monkeypatch` |
| Provider request/response/stream normalization | `test_provider.py`, `test_litellm_gateway.py`, `test_chat.py` | Fake session |
| Local-first routing and fallback policy | `test_router_static.py`, `test_facade_contract.py` | Pure `StaticRouter` |
| Strict routing-model JSON | `test_router_gemma.py` | Fake model client |
| Runtime readiness, timeout, and cleanup | `test_runtime.py` | Fake process/probe |
| Composition and facade boundary | `test_bootstrap.py`, `test_facade_contract.py` | Fake registry/provider |
| Observability and stable errors | `test_observability.py` | In-memory logger and request IDs |
| Import direction | `test_import_boundaries.py` | AST walk |

## Milestone checks

These files are part of the offline pytest suite unless marked as the
separate Node gate. They provide regression coverage, not real process
startup/shutdown acceptance.

| Milestone | Existing checks | Coverage |
| --- | --- | --- |
| M9 | `tests/test_m9_request_admission.py`, `tests/test_m9_launcher_failures.py`, `tests/test_m9_runtime_stop.py` | Request admission and launcher/runtime failure and stop-state contracts |
| M10 | `tests/test_m10_local_config.py`, `tests/test_m10_profile_selection.py`, `tests/test_m10_doctor_paths.py`, `tests/test_m10_gateway_setup.py` | Local configuration, profile selection, doctor paths, and opt-in Gateway setup contracts |
| M11 | `tests/test_m11_chat_contract.py`, `tests/test_m11_chat_integration.py`, `tests/test_m11_web_behavior.py`; separate Node gate: `tests/web_chat.test.cjs` | Conversation bounds, API/facade/provider integration without model or network I/O, and bundled UI behavior |
| M12 / R1 | `tests/test_m12_readiness_probe.py`, `tests/test_m12_acceptance_evidence.py`, `tests/test_m12_acceptance_windows.py` | Lightweight readiness; offline evidence preparation, PID/creation-time ownership, conservative cleanup classification, and fake Windows API queries |

## Attempt budget and evidence

Share a maximum of three attempts across each validation path, including
setup failures and work by helpers. After an informative result, do not repeat
the same command with the same inputs and environment; change the hypothesis
or conditions, or record the path as deferred or blocked. Record the command,
environment/setup, collected and passed counts, observed side effects, and
result classification (`PASS`, `DEGRADED`, `DEFERRED`, or `BLOCKED`). Classify
known failures as setup, assertion, or isolation failures.

## Manual local-model smoke

After starting a local OpenAI-compatible server yourself, run:

```powershell
& .\.venv\Scripts\python.exe tests/manual_chat_smoke.py --base-url http://127.0.0.1:8080 --model gpt-oss
```

Use the exact model alias advertised by the running endpoint; `gpt-oss` is the
current generated local profile alias. This check is local-only and is not a
CI gate. Stop only a server you started and own; leave externally managed
servers running and follow their owner's lifecycle. Do not place endpoints or
output in collected tests or committed configuration. This check does not
test the launcher shutdown path.
