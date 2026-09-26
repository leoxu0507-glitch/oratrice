# M7-02 project virtual environment

- Date: 2026-08-21 (Asia/Hong_Kong)
- Scope: create and validate the project virtual environment for the canonical
  Windows checkout at `D:\AI\projects\Oratrice`.
- Result: `PASS` for the resulting project environment and acceptance checks.
  The first setup process returned exit code 1 with an empty script diagnostic
  after creating/installing the environment; the final state was independently
  verified below. No service or model was started.

## Inputs and command

The selected base interpreter was the explicitly requested absolute path:

```text
<USER_PROFILE>\AppData\Local\Programs\Python\Python313\python.exe
```

The setup command was run from the project root with process-scoped execution
policy bypass only:

```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\scripts\setup_oratrice.ps1 -Python '<USER_PROFILE>\AppData\Local\Programs\Python\Python313\python.exe'
```

The script created `D:\AI\projects\Oratrice\.venv` and installed from
`requirements.txt -c constraints.txt`. A subsequent direct venv-pip diagnostic
reported every requirement as already satisfied and exited 0; it was used once
only to expose the otherwise empty setup-script pip diagnostic.

## CheckOnly acceptance

The required non-mutating check was run once and exited 0:

```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\scripts\setup_oratrice.ps1 -Python '<USER_PROFILE>\AppData\Local\Programs\Python\Python313\python.exe' -CheckOnly
```

The script reported `PASS` for all six direct dependencies:

| Distribution | Required constraint | Installed |
| --- | --- | --- |
| PyYAML | `>=6.0` / `==6.0.3` | `6.0.3` |
| requests | `>=2.31` / `==2.34.2` | `2.34.2` |
| fastapi | `>=0.115,<1` / `==0.115.14` | `0.115.14` |
| uvicorn | `>=0.29,<1` / `==0.29.0` | `0.29.0` |
| pytest | `>=8.0` / `==9.1.1` | `9.1.1` |
| httpx | `>=0.27,<1` / `==0.28.1` | `0.28.1` |

## Runtime evidence

Collected from `D:\AI\projects\Oratrice\.venv\Scripts\python.exe` after
installation:

```text
sys.executable=D:\AI\projects\Oratrice\.venv\Scripts\python.exe
version=3.13.5 (tags/v3.13.5:6cb20a2, Jun 11 2025, 16:15:46) [MSC v.1943 64 bit (AMD64)]
bitness=64
pip 25.1.1 from D:\AI\projects\Oratrice\.venv\Lib\site-packages\pip (python 3.13)
pip check: No broken requirements found.
```

The base interpreter evidence was Python 3.13.5, 64-bit, with pip 26.1.2.
No global PATH, registry, execution-policy, service, model, product-code,
requirements, or constraints changes were made.

## Caveat and bounded attempts

The first invocation under the restricted shell could not create the target
directory (`WinError 5`, access denied). The one approved elevated invocation
created the venv and installed the pinned distributions, but the wrapper then
returned exit code 1 with no diagnostic. A final setup invocation against the
already-populated venv reproduced that empty pip diagnostic. The one direct
venv-pip diagnostic/install fallback exited 0 and showed all requirements
already satisfied. `-CheckOnly` and `pip check` both passed; no further install
retries are warranted under the bounded validation policy.
