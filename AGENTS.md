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
- The repository-bundled thin UI is served by the Core API at `/ui/` and is the
  default launcher destination after `/live` succeeds. It is a same-origin
  client for `/live`, `/ready`, and `/chat`; it does not own routing,
  persistence, models, tools, or provider logic.
- OpenWebUI remains an external optional UI. A copied profile may probe/open an
  already healthy external UI, but Oratrice does not install, configure, or own
  its process.

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
