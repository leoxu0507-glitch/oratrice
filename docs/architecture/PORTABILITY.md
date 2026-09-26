# Windows launcher portability

`Start-Oratrice.exe` is a thin bootstrap. It resolves the Python interpreter
without assuming a particular drive, checkout, or user profile, then runs
`scripts/launch_oratrice.py` with the executable directory as its working
directory.

Python discovery is deterministic:

1. If `ORATRICE_PYTHON` is set, it must be an absolute path to an existing
   executable. An invalid or missing path is reported as a configuration
   error; the launcher does not silently fall through to another interpreter.
2. `<project root>\\.venv\\Scripts\\python.exe`.
3. `<project root>\\..\\..\\infrastructure\\litellm\\.venv\\Scripts\\python.exe`,
   normalized from the project root.
4. `python.exe` in the process `PATH`, searched in PATH order.

The launcher does not modify `PATH`, the registry, execution policy, or any
machine-wide setting. `--dry-run --no-browser` is forwarded to the Python
launcher, so offline validation can inspect the plan without starting model,
gateway, API, or browser processes.
