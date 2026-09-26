# Reproducible Windows environment

Oratrice keeps its Python environment local to the checkout.  The supported
bootstrap is `scripts/setup_oratrice.ps1`; it does not install Python, change
the machine or user `PATH`, change execution policy, write the registry, or
create credentials.

## Prerequisites

Run PowerShell from `D:\AI\projects\Oratrice` (or use an equivalent checkout
root).  A Python 3.10-or-newer interpreter is required.  The bootstrap chooses
one in this order:

1. an absolute path passed with `-Python`;
2. the absolute path in `ORATRICE_PYTHON`;
3. the Python 3 interpreter selected by `py.exe -3`.

The selected interpreter is reported before any environment work.  An
explicit path that does not exist, cannot run, or is older than Python 3.10 is
an error; the script does not silently fall through to another interpreter.

## Create and install

The default environment is `<project root>\.venv`:

```powershell
cd D:\AI\projects\Oratrice
.\scripts\setup_oratrice.ps1
```

The install command is always run by the venv interpreter created or found at
`<venv>\Scripts\python.exe`:

```text
<venv>\Scripts\python.exe -m pip install -r <project root>\requirements.txt -c <project root>\constraints.txt
```

No global `pip` is used.  The requirements file declares PyYAML, requests,
FastAPI, uvicorn, pytest, and httpx.  `constraints.txt` records the M6-verified
exact versions of those six direct dependencies; it is a direct-dependency
baseline, not a lock of transitive packages.  Normal setup passes both files
to pip:

```text
<venv>\Scripts\python.exe -m pip install -r requirements.txt -c constraints.txt
```

The script checks each package's import and requirements version constraints
after installation.  `-CheckOnly` intentionally checks only the ranges in
`requirements.txt`, so an existing environment can be diagnosed without
requiring the M6 baseline versions.

An alternate location must be explicit.  Relative values are resolved from
the project root; absolute values are accepted as supplied:

```powershell
.\scripts\setup_oratrice.ps1 -VenvPath work\oratrice-venv
.\scripts\setup_oratrice.ps1 -Python C:\Python313\python.exe -VenvPath D:\venvs\oratrice
```

The parent directory of an explicit venv path must already exist.  An
existing path is never deleted or rebuilt automatically; an incomplete venv
produces a clear error so the operator can choose a new explicit path.

## Inspect without installing

Use `-CheckOnly` to verify the selected base interpreter, an existing venv,
and every required import/version without creating files or invoking pip:

```powershell
.\scripts\setup_oratrice.ps1 -CheckOnly
.\scripts\setup_oratrice.ps1 -Python C:\Python313\python.exe -VenvPath work\oratrice-venv -CheckOnly
```

`-CheckOnly` fails when the venv is absent or incomplete, or when a required
package is missing or outside its declared constraint.  It does not activate
the environment and does not modify `ORATRICE_PYTHON`; use the reported
absolute interpreter for tests and launcher commands:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
```

## Secrets and operational boundaries

This setup flow does not read or generate API keys, write `.env` files, or
persist any secret.  Keep optional runtime credentials in the process
environment or a secret manager as described in `README.md`.  Installing
dependencies may contact the package index through pip when the operator
explicitly runs the normal (non-`-CheckOnly`) command; the static contract
tests never invoke setup, pip, Python, a model, or a network endpoint.

For a machine with no Python installation, the expected remedy is to install
an approved Python 3.10+ runtime or pass `-Python` to an existing absolute
interpreter.  The bootstrap will not download a runtime or alter global
configuration on the operator's behalf.
