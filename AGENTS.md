# Oratrice project working agreements

This file records Oratrice-specific boundaries and release evidence. The
canonical Windows checkout used by the launcher and validation records is
`D:\AI\projects\Oratrice`.

## Architecture and protected boundaries

- The provider-neutral request path is `bundled web UI/other frontend -> Core
  API/CoreFacade -> router -> provider manager/adapter -> local provider`.
- `core/`, `router/`, `entities/`, and `oratrice_api/` are the provider-neutral protection zone. They do not import LiteLLM, provider SDKs, HTTP clients,
  sockets, or process APIs, and they do not embed provider URLs or model
  identities.
- Concrete transport and credentials belong behind `providers/`. Process
  startup, health-gated ordering, and cleanup belong to `launcher/`; the
  router returns a decision and does not start a model or call a network.
- `config/profiles/live.yaml` is the declarative live composition source.
  Loading it validates references and expands environment values but does not
  start a process or contact a provider.
- The repository-bundled thin UI is served by the Core API at `/ui/` and is
  the default launcher destination after `/live` succeeds. It is a same-origin
  client for `/status`, `/chat`, and `/chat/stream`. It owns explicit, bounded,
  off-by-default browser-profile conversation retention and export; Core,
  Router, and API remain stateless for conversations. It does not own routing,
  models, tools, or provider logic.
- OpenWebUI remains an external optional UI. A copied profile may probe/open an
  already healthy external UI, but Oratrice does not install, configure, or own
  its process.
- M15's standalone `frontends/pet/` is an independent loopback API client. It
  reads only `/status` and opens the same origin's `/ui/` on user activation.
  It never starts or stops Core/models, handles prompts, or imports concrete
  providers. Tk window creation belongs only to its explicit entry point.
  The installed OpenPets 3.2.1 SDK cannot consume the loopback API; that
  integration remains deferred following the operator's standalone choice.

## Windows commands used by this project

Run commands from `D:\AI\projects\Oratrice` unless a command says otherwise.

```powershell
py -3 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\Start-Oratrice.exe --dry-run --no-browser
.\Start-Oratrice.exe --no-browser
.\Start-Oratrice.exe --with-qwen
& $env:ORATRICE_PYTHON -m pytest -q
```

The default live UI is `http://127.0.0.1:8000/ui/`; use `--no-browser` for a
headless launch. The live profile's `ui_url`/`ui_health_url` are declarative
launcher metadata and may be replaced in a copied profile when an external UI
is intentionally selected.

The Core API runtime command declared by the live profile starts
`oratrice_api.main:app` with `-m uvicorn` on `127.0.0.1:8000`. The historical
M5 gate command is:

```powershell
$env:PYTHONPATH = "D:\AI\infrastructure\litellm\.venv\Lib\site-packages;D:\AI\projects\Oratrice\work\oratrice-test-venv\Lib\site-packages"
$env:PYTHONDONTWRITEBYTECODE = "1"
python -B -m pytest -q -p no:cacheprovider tests/test_m5_release_gate.py
```

## Bounded validation evidence

- M11/M13.1 conversation history remains request-scoped: `/chat` accepts
  optional complete text `history` pairs, and omitting it preserves legacy
  calls. Core preserves roles for the provider, and Router remains
  decision-only. The bundled UI is page-only by default and may use bounded,
  explicit opt-in same-origin browser storage and export. API, Core, and
  Router retain no conversation state. Do not silently trim messages or evict
  stored conversations.
- JavaScript behavior, archive-data, and browser-store tests run separately
  with `node --test tests/web_chat.test.cjs tests/conversation_data.test.cjs
  tests/conversation_store.test.cjs tests/stream_client.test.cjs`; no npm dependency or frontend build.
  Keep pytest free of new Node subprocesses and model/service startup.
- M14 streaming is opt-in in the bundled UI. Stop ends HTTP delivery, not
  guaranteed inference. One worker owns stream setup, iteration, and close;
  it drains discarded output after disconnect and keeps the shared
  chat/route admission slot until its work and cleanup end. Never close an
  executing provider generator from another thread. Interrupted turns stay
  visibly partial and do not enter context, local retention, or exports.
- M15 `/status` tracks the actual shared operation slot, including stream
  draining after Stop. Late callbacks carry an admission generation token.
  Readiness uses only an explicit read-only checker, a five-second cache,
  single-flight probes, and bounded stale results. Never fall back to
  `facade.health()` from status polling or expose prompts/provider internals.
- M10 adds generated `config/profiles/local.yaml` and `config/gateway.local.yaml`;
  these are ignored operator files. Service entry points prefer the local
  profile when present, otherwise the historical live profile. Templates and
  `scripts/configure_local.py` are the reproducible source.
- Core and Gateway have separate `.venv` and `.gateway-venv` installations.
  Use `scripts/setup_oratrice.ps1 -Gateway` for the latter. Keep the external
  historical infrastructure venv untouched during deployment tests.
- On the validation host use `-p no:cacheprovider` and an explicit writable
  `--basetemp` with an existing parent directory for pytest. Default AppData
  temporary paths have produced setup errors.
- A validation owner tracks one attempt budget across helpers and agents;
  count setup failures and do not reset a budget by renaming a helper.

- Every validation path has at most three attempts. Do not rerun the same
  command with the same condition after an informative result; change the
  hypothesis or record the path as deferred/blocked instead.
- Record the command, environment/setup, collected and passed counts, side
  effect observations, and the result classification (`PASS`, `DEGRADED`,
  `DEFERRED`, or `BLOCKED`). For a failure, classify the cause as `setup`,
  `assertion`, or `isolation` when that distinction is known.
- Launcher cleanup evidence must distinguish listener closure from process
  reaping. M8 exhausted three bounded cleanup paths (Codex ConPTY observation,
  managed handler harness, and native handler harness); the latter two failed,
  their exact-PID cleanup succeeded, and their unverified handler changes were
  reverted. Do not claim automatic cleanup from dry-run or port state alone.
- Use `luna_worker` for a bounded subtask with a clear file/interface boundary;
  release conclusions and evidence classification remain in the owning task.
