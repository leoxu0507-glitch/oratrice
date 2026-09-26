# M7-04 runtime wiring

- Date: 2026-08-21 (Asia/Hong_Kong)
- Scope: switch the live launcher overrides to the validated M7-03 LiteLLM
  environment and the independent M7-02 Oratrice project environment.
- Result: `PASS` for the offline path-wiring checks below. No service, model,
  browser, network request, or credential value was started or contacted.

## Declarative wiring

`config/profiles/live.yaml` now declares these overrides (relative to the
profile directory, then normalized by `ConfigurationLoader`):

| Target | Override | Resolved executable |
| --- | --- | --- |
| LiteLLM Gateway | `../../../../infrastructure/litellm/.venv-m7-03/Scripts/litellm.exe` | `D:\AI\infrastructure\litellm\.venv-m7-03\Scripts\litellm.exe` |
| Core API | `../../.venv/Scripts/python.exe` | `D:\AI\projects\Oratrice\.venv\Scripts\python.exe` |

Both resolved files exist. The gateway and Core API use different venv
directories; the legacy LiteLLM `.venv` directory remains untouched as a
rollback reference and is not selected by either live override.

`D:\AI\infrastructure\litellm\start.bat` is synchronized to invoke
`.venv-m7-03\Scripts\litellm.exe`. `config.yaml`, the legacy `.venv`, and
provider-neutral Core logic were not changed.

## Offline verification

Command, run from `D:\AI\projects\Oratrice` with the project interpreter:

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
& .\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider `
  tests/test_m7_runtime_paths.py `
  tests/test_launcher_plan.py `
  tests/test_launcher_orchestrator.py `
  tests/test_m4_launcher_api.py
```

Observed result: `15 passed in 0.57s` on the final (third and last) bounded
attempt. Path parsing was absolute, both selected executables existed,
Core/Gateway interpreter directories were isolated, and no old `.venv` path was
present in the live plan or start script. The test suite was static/injected and
did not launch processes or contact endpoints.
