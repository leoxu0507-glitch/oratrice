# M12 Installation Validation

Date: 2026-11-02
Result: **PASS** — isolated Core and Gateway installation plus offline preflight. This report does not claim the live default-model chain.

## Source snapshot

- Exported the current public working-tree files into a fresh checkout at <clean checkout>\work\m12 install candidate using git ls-files --cached --others --exclude-standard -z.
- Copied 186 files totaling 1,037,694 bytes. The export omitted Git metadata and applied explicit filters for .git, .env*, virtual environments, logs, models, and the root work directory. No listed source files matched the filters.
- The canonical working tree contained existing M9–M11 changes at export time. This is a working-tree snapshot; no clean commit or final commit identity is claimed.
- Candidate setup assets matched the canonical files by SHA-256 at final reconciliation:

| File | SHA-256 |
| --- | --- |
| requirements.txt | 0A9486A4E0E3517DC74F445C63BB44FBEB7EDA78B78D1A4A4FEFAB604BC35907 |
| constraints.txt | E96607EB15E4F744B8F5B93A774A535F0F2AD8F54BD7A81A94E8ABC573327A47 |
| requirements-gateway.txt | F1FF2D370D985532C10A9BAECD71924D947F774511EC604DEA665F7CF2B468C1 |
| scripts/setup_oratrice.ps1 | B635C061BE75559D9EFB9DA7B7B3FBB691F41D91BE03380615045B548B208122 |
| scripts/configure_local.py | 5113364708763C26B92BA1208950E3A1C694500685CDDF338ED714A7658C38FC |

## Environment setup

The base interpreter was identified from the canonical environment's sys._base_executable: Python 3.13.5, 64-bit. Both environments were created fresh in the candidate: Core at .venv and Gateway at .gateway-venv.

Setup used powershell.exe with NoLogo, NoProfile, NonInteractive, and process-scoped ExecutionPolicy Bypass. TEMP and TMP pointed to <clean checkout>\work\m12 install candidate\_m12-temp. All setup attempts used PIP_RETRIES=0, PIP_DEFAULT_TIMEOUT=30, and PIP_DISABLE_PIP_VERSION_CHECK=1. No machine or user execution policy, Python installation, or environment variables were changed.

| Environment | Attempt | Result |
| --- | --- | --- |
| Core | 1, default command context | Setup failure before dependencies installed. The PyPI request timed out and pip reported no available Pydantic versions while resolving FastAPI. A separate elevated check later received HTTP 200 from PyPI, identifying this as execution-context network access. |
| Core | 2, elevated network context | PASS. The setup script installed requirements.txt with constraints.txt, ran pip check, and imported/version-checked all six entries. |
| Gateway | 1, elevated network context | PASS. The setup script installed requirements-gateway.txt, ran pip check, and imported/version-checked LiteLLM. |

Core attempt 1 used PIP_NO_CACHE_DIR=1. The pip cache was empty at the time (zero HTTP cache files and zero locally built wheels); the subsequent successful installs used normal cache behavior. The failed attempt created only the new venv before pip resolution stopped. Attempt counts were retained.

Verified Core package versions:

| Package | Version |
| --- | --- |
| PyYAML | 6.0.3 |
| requests | 2.34.2 |
| fastapi | 0.115.14 |
| uvicorn | 0.29.0 |
| pytest | 9.1.1 |
| httpx | 0.28.1 |

Gateway LiteLLM version: 1.74.3. Both setup-script pip check runs and required import/version checks passed.

## Local configuration

The configuration generator exited 0 and created the ignored local profile and Gateway config in the candidate. The canonical ignore rules matched both generated config paths and both virtual-environment paths.

The generator used the supplied existing files: llama-server.exe (9,216 bytes), openai_gpt-oss-20b-MXFP4.gguf (12,109,565,760 bytes), and gemma-3n-E4B-it-Q5_K_M.gguf (4,947,998,304 bytes). It created config/profiles/local.yaml (5,521 bytes) and config/gateway.local.yaml (417 bytes). No model contents were loaded.

## Offline Doctor and dry-run

Strict Doctor exited 0. It reported 7 checks: 6 PASS, 1 WARN, 0 FAIL. The overall report status is WARN because of this single non-blocking check:

- Code: environment
- Message: environment variable(s) absent; launcher may generate them: ORATRICE_LITELLM_MASTER_KEY

This is the expected process-local Gateway key that the launcher can generate. A second human-output Doctor invocation was used only to capture the warning details; it also exited 0.

The launcher dry-run exited 0 with --no-browser and planned GPT-OSS, Gemma Router, LiteLLM Gateway, and Core API. It did not start these targets. Before and after Doctor and dry-run, Windows listener snapshots reported zero entries and no additions or removals; the llama-server process count stayed at zero. No browser was requested, no model was loaded, and no model request was sent by this install/preflight gate.

No pytest suite or live-model chain was run here. The live default-chain acceptance is a separate gate owned by the parent task.
