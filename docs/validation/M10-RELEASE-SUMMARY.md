# M10 portable installation and configuration

Date: 2026-11-01 (Asia/Hong_Kong).

Overall disposition: **DEGRADED**. Portable installation and offline acceptance
passed. Hardware stability and the M9 real-model/user-console acceptance remain
deferred; this milestone does not change their disposition.

## Delivery and dependency inventory

| Work item | Delivered | Evidence/status |
| --- | --- | --- |
| M10.1 Dependency inventory | Core requirements/constraints, Gateway pin, native runtime and model prerequisites | PASS within documented scope |
| M10.2 Deployment assets | Local-only profile template, Gateway template, explicit optional cloud supplement, configuration generator | PASS offline and generated-config checks |
| M10.3 Installation/diagnostics | Isolated Gateway setup, strict required-path checks, safe environment expansion, actionable field labels | PASS on clean Windows/Python 3.13.5 checkout |
| M10.4 Runtime settings | Context and thread controls, one server slot, CPU-first Gemma | Configuration delivered; hardware stability DEFERRED |
| M10.5 Portable regression | Full suite without external infrastructure-file reads, full-suite CI definition | 180 passed locally in the clean checkout; remote CI not dispatched |

Core uses a project `.venv` with the six direct versions in `constraints.txt`.
Gateway uses a separate `.gateway-venv` with `litellm[proxy]==1.74.3`. These are
direct dependency pins, not a complete transitive lock or a reproducibility
claim for every future package index state. Both clean environments passed the
installer's `pip check`. Python itself, llama.cpp with compatible runtime DLLs,
and compatible GPT-OSS/Gemma GGUF files are user-supplied dependencies.

The repository now includes everything required to describe the local gateway
installation. The existing external LiteLLM installation is not a prerequisite
for the new deployment, nor a file dependency of the ordinary test suite.

## Local configuration contract

`scripts/configure_local.py` accepts explicit existing runtime/model files and
generates ignored `config/profiles/local.yaml` and `config/gateway.local.yaml`.
It uses YAML serialization, supports paths containing spaces, refuses existing
output files, retains absolute external asset paths, and writes no credential.
In-project Python/Gateway executable paths are relative to the profile. The
generator can run before the default virtual environments exist; strict Doctor
then reports any missing executable.

Launcher, standalone API, and Doctor prefer the generated local profile, with
legacy `live.yaml` as fallback. Explicit profile overrides retain precedence.
The local template contains GPT-OSS/Gemma only. Optional cloud configuration is
an explicit supplemental example and is never merged automatically.

The Gateway receives `LITELLM_LOCAL_MODEL_COST_MAP=True`: inspection of the
installed LiteLLM 1.74.3 source confirmed that this prevents its import-time
remote model-cost-map fetch. Setup applies the same switch only inside its
dependency-check Python child. That child uses `-B` to avoid bytecode writes.

## Corrections found during integration

- Windows PowerShell unrolls a one-entry requirement list into a scalar. The
  real Gateway setup initially failed on `.Count`; receiving the function
  output with `@(...)` fixed the single-dependency case.
- Generic path detection treated the name `defaults.profile` as a file path
  because it contains `file`. The loader now preserves this label as text;
  a regression test also confirms real `config_path` values still resolve.
- Tests previously read external LiteLLM config/start files or asserted the
  maintainer's absolute checkout. They now validate repository templates and
  profile-relative resolution. Runtime installation existence is checked by
  Doctor/manual acceptance rather than assumed by the offline suite.

## Clean-checkout validation

The owning task exported the current public source set into a new **C-drive
directory containing spaces**, without `.git`, virtual environments, local
configuration, logs, weights, or runtime output. This was an export of the
uncommitted working tree, not a download of the older public GitHub release.
No pre-existing environment was copied, and `PYTHONPATH` was cleared for tests.

Commands below ran from that clean checkout with Python 3.13.5:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup_oratrice.ps1 -Python <base-python>
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup_oratrice.ps1 -Python <base-python> -Gateway
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup_oratrice.ps1 -Python <base-python> -CheckOnly
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup_oratrice.ps1 -Python <base-python> -Gateway -CheckOnly
.gateway-venv/Scripts/litellm.exe --help
.venv/Scripts/python.exe -B scripts/configure_local.py --llama-server <existing-exe> --gpt-model <existing-gguf> --router-model <existing-gguf>
./Start-Oratrice.exe doctor --strict-paths --json
./Start-Oratrice.exe --dry-run --no-browser
.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider --basetemp work/m10-pytest-final
```

- Core: all six baseline imports and `pip check` passed.
- Gateway: version 1.74.3 import, `pip check`, `CheckOnly`, and CLI help passed.
- Generated profile: strict Doctor returned 6 PASS, 1 WARN, 0 FAIL, exit 0.
  The warning is the absent process-local master key, which the launcher can
  generate. All seven distinct required asset paths were present.
- Dry-run: four ordered targets PLANNED, UI NOT_REQUESTED, exit 0.
- Standalone API: selected the generated local profile without starting a
  model or listener.
- Final complete suite: **180 passed, 1 warning in 3.47s**. The warning is a
  third-party Starlette/AnyIO deprecated alias, not a failed test.

## Attempt ledger

| Gate | Attempts and result |
| --- | --- |
| Configuration worker | 1: host temp/cache setup errors, 4 checks passed; 2: 7 passed. Final environment flags were covered by the owning task's integrated suite. |
| Doctor worker | 1: host temp/cache setup errors; 2: 11 passed. Final mmproj/config/service-argument cases were covered by the integrated suite. |
| Setup worker | 1: 6 passed; 2: 7 passed after import-network safeguard. |
| Clean Core installation | 1: script execution policy blocked before setup; 2: sandbox/default-temp `ensurepip` failure; 3: dedicated writable temp and escalated execution succeeded. The partial venv was repaired with bundled ensurepip before setup resumed. No fourth installation. |
| Clean Gateway installation | 1: one-entry array bug; 2: corrected installer succeeded. |
| Gateway CheckOnly | 1: isolated sandbox import failure; direct diagnostic import succeeded; 2: passed with the installation's execution context and dedicated temp. The exact first import failure was not proven. |
| Full clean suite | 1: 179 passed, 1 warning; after the real profile-label bug and `-B` correction, 2: 180 passed, 1 warning. No third run needed. |
| Generated strict Doctor | 1: a spurious profile-path warning; 2: corrected loader, required paths PASS, only generated-key warning remains. |

Execution-policy bypass was process-scoped and applied only to reviewed project
scripts. No machine execution policy, global Python installation, driver,
external LiteLLM environment, or cloud credential was changed. The clean
verification checkout and its two environments remain outside the source tree
for inspection; generated configuration and installer logs are not published.

## Hardware boundary and remaining acceptance

Preflight observed 735592 KiB free physical memory out of 16395004 KiB. GPU
telemetry reported an RTX 4060 Laptop GPU with 1028 MiB used and 6929 MiB free.
Ports 4000/8000/8080/8082/8090 had no listeners. Large models were not loaded.

The supplied context size 2048, one server slot, CPU-first Gemma, configurable
GPU layers and thread count are explicit starting parameters. The local
llama.cpp help confirmed the relevant options exist. They are not measured
stable settings for the complete model chain or other hardware. Reclaiming
enough host memory and running the M9 real-model/console acceptance remains
necessary before a release can be called fully usable. M11/M12 are not part
of this change, and public GitHub refs/releases are unchanged.
