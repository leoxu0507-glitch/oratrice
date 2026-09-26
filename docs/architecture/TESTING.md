# V1 testing and isolation guide

The contract suite is designed to run on a clean machine with no model
weights, local runtime, network route, or cloud credential.  It verifies the
boundaries in this directory without turning the test runner into a service
orchestration tool.

## Standard commands

From the repository root:

```powershell
python -m pytest -q
```

Use `py -m pytest -q` when the Windows Python launcher is the available
entrypoint.  Installing dependencies is an environment setup step; the test
command itself must not download packages or start a model.

## Isolation rules

- Provider and gateway tests inject a requests-compatible fake session.
- Runtime tests inject process runners, readiness probes, and sleepers.
- Router-model tests inject a fake client that returns a fixed JSON decision.
- Facade tests inject a provider registry and assert normalized responses,
  streams, errors, provider identity, and request correlation IDs.
- Import-boundary tests inspect ASTs and do not import a transport SDK.
- `tests/manual_chat_smoke.py` is deliberately not named `test_*.py`; it is
  the sole opt-in path for a real local model request.

Adding a test that opens a socket, starts a subprocess, loads model weights,
or reads a cloud secret by default is a contract violation.  Put such a check
behind an explicit manual command and document its prerequisites.

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

## Manual local-model smoke

After starting a local OpenAI-compatible server yourself, run:

```powershell
python tests/manual_chat_smoke.py --base-url http://127.0.0.1:8080 --model gpt-oss
```

This check is local-only and is not a CI gate.  Stop the server after the
check; do not place its endpoint or output in collected tests or committed
configuration.
