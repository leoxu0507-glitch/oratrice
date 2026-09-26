# M7-01 Python discovery audit

- Date: 2026-08-21 (Asia/Hong_Kong)
- Scope: read-only Windows Python discovery for `D:\AI\projects\Oratrice`.
- Result: `DEFERRED` — no runnable base Python or local installer was found. No
  download, installation, virtual-environment creation, PATH change, or
  execution-policy change was attempted.

## Project requirements

The project setup script (`scripts\setup_oratrice.ps1`) accepts an explicit
absolute `-Python` path first, then `ORATRICE_PYTHON`, then `py.exe -3`. Its
`Get-PythonVersion` check requires Python `3.10.0` or newer; neither the
requirements nor the constraints file declares an upper Python bound.

Runtime and test requirements are:

| Distribution | Requirement | M6 constraint |
| --- | --- | --- |
| PyYAML | `>=6.0` | `6.0.3` |
| requests | `>=2.31` | `2.34.2` |
| fastapi | `>=0.115,<1` | `0.115.14` |
| uvicorn | `>=0.29,<1` | `0.29.0` |
| pytest | `>=8.0` | `9.1.1` |
| httpx | `>=0.27,<1` | `0.28.1` |

`-CheckOnly` is the non-mutating project acceptance path: it validates the
selected interpreter, an existing `.venv`, and imports/versions without pip or
network access. Normal setup creates `.venv` and installs with
`requirements.txt -c constraints.txt`.

## Read-only discovery evidence

Commands were run from the available Windows PowerShell context; no network
command was used.

- `Get-Command py/python/winget -CommandType Application`:
  `C:\Windows\py.exe` is present (`py.exe` file version `3.13.5150.1013`),
  while `python` and `winget` are absent.
- `py -0p`: `No installed Pythons found!`.
- Host/process architecture: `Is64BitOperatingSystem=True`,
  `Is64BitProcess=True`, `PROCESSOR_ARCHITECTURE=AMD64` (64-bit Windows).
- PythonCore registry roots (`HKCU` and both `HKLM` 64/32-bit paths): no
  entries were found.
- Uninstall registry entries contain Python 3.13.5 (64-bit) components
  (Core Interpreter, Executables, Standard Library, pip Bootstrap, Tcl/Tk,
  Development Libraries, Test Suite, Documentation, and Add to Path) plus the
  Python Launcher. These are installer-component records, not proof of a
  runnable interpreter.
- Common user/Program Files Python locations (`<USER_PROFILE>\AppData\Local\Programs\Python\Python*`,
  `%ProgramFiles%\Python*`, `%ProgramFiles(x86)%\Python*`, `C:\Python*`, and
  `D:\Python*`) contained no discoverable Python executable.
- The existing `D:\AI\infrastructure\litellm\.venv` has `pyvenv.cfg` with
  `version = 3.13.5`, but its `Scripts\python.exe` failed to start (exit code
  101, `Unable to create process`). The cfg points at the unavailable base
  executable `<USER_PROFILE>\AppData\Local\Programs\Python\Python313\python.exe`.
  It is not a safe Oratrice interpreter substitute.
- Searched local pip/temp/download/Chocolatey/WinGet cache locations contained
  no Python installer or pip package cache. The only matching temp item was
  `<USER_PROFILE>\AppData\Local\Temp\python-languageserver-cancellation`.

## Reuse decision and version basis

There is no currently verified formal Python that Oratrice can reuse. The
launcher exists, but it reports no installed runtimes; the registry remnants
and broken LiteLLM venv do not change that conclusion.

The evidence-based target for a future install is a 64-bit CPython 3.13.5
interpreter, because that is the version recorded by the existing venv and
installer components on this AMD64 host. This is a compatibility target, not a
claim that the runtime is currently installed or that dependency resolution has
been validated. The hard project floor remains Python 3.10+. Obtaining an
official installer would require network access; it was not requested or used
for this audit.

## Minimal safe installation plan (not executed)

1. Obtain an approved official 64-bit CPython 3.13.5 installer (network or
   approved local media is required; no local installer was found).
2. Install it according to machine policy without relying on the stale venv;
   retain the absolute interpreter path and avoid a machine-wide PATH or
   execution-policy change.
3. From the canonical project root, use the explicit interpreter path with
   `scripts\setup_oratrice.ps1`. The script owns venv creation and constrained
   dependency installation; do not invoke global `pip`.

## Exact acceptance commands (run only after an approved install)

Replace `<python.exe>` with the verified absolute CPython path.

```powershell
Set-Location -LiteralPath 'D:\AI\projects\Oratrice'
& '<python.exe>' -B -c "import sys,struct; print(sys.executable); print(sys.version); print(struct.calcsize('P')*8)"
& .\scripts\setup_oratrice.ps1 -Python '<python.exe>'
& .\scripts\setup_oratrice.ps1 -Python '<python.exe>' -CheckOnly
& .\.venv\Scripts\python.exe -m pytest -q
& .\Start-Oratrice.exe --dry-run --no-browser
```

Expected evidence is Python `>=3.10`, 64-bit output, successful constrained
dependency checks from `-CheckOnly`, a passing pytest result, and a successful
launcher dry run. These commands were not run during the discovery audit.

## M7-01 installation follow-up (2026-08-21)

The requested target was rechecked before any installer action. It already
contains a complete runnable installation at
`<USER_PROFILE>\AppData\Local\Programs\Python\Python313\python.exe`.
The absolute interpreter checks passed:

```text
sys.executable=<USER_PROFILE>\AppData\Local\Programs\Python\Python313\python.exe
version=3.13.5
bits=64
pip 26.1.2 from <USER_PROFILE>\AppData\Local\Programs\Python\Python313\Lib\site-packages\pip (python 3.13)
venv --help: exit code 0 (usage text returned)
```

`C:\Windows\py.exe -0p` still returns `No installed Pythons found!`, so the
launcher registration is not usable for selection. Oratrice should use the
absolute path above (or `-Python`/`ORATRICE_PYTHON`) until launcher registration
is separately repaired.

The official installer URL reserved for this operation was
`https://www.python.org/ftp/python/3.13.5/python-3.13.5-amd64.exe`, with the
explicit temporary path
`<USER_PROFILE>\AppData\Local\Temp\oratrice-python-3.13.5-amd64.exe`.
Two read-only download attempts failed before an installer file was obtained:

- PowerShell `Invoke-WebRequest`: `Authentication failed, see inner exception.`
- native `curl.exe`: Schannel `SEC_E_NO_CREDENTIALS (0x8009030e)` (exit 35).

The requested temporary path does not contain a partial file. Consequently,
there is no downloaded byte stream to Authenticode-verify, and no signer,
SHA256, or size can honestly be recorded. The signature gate was not bypassed.
The installer process was never started (no PID and no persistent installer
change); the current-user `InstallAllUsers=0`, `PrependPath=0` plan therefore
made no PATH, execution-policy, repository, or infra changes.

Final classification: `DEFERRED` for installer download/repair because the
target runtime is already valid and the environment cannot establish TLS
credentials. `PASS` for the requested absolute Python, pip, and venv runtime
checks. No project virtual environment was created.
