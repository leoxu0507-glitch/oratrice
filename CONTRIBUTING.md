# Contributing to Oratrice

Thank you for helping improve Oratrice. The project is deliberately local-first,
provider-neutral, and conservative about expanding the Core contract.

## Development setup

Oratrice is currently validated on native Windows with Python 3.13. From a
PowerShell prompt in the repository root:

```powershell
.\scripts\setup_oratrice.ps1
$env:ORATRICE_PYTHON = (Resolve-Path .\.venv\Scripts\python.exe).Path
& $env:ORATRICE_PYTHON -m pytest -q -p no:cacheprovider
```

The ordinary test suite is offline and must not start model processes, open
network listeners, launch a browser, or contact cloud APIs. Live model checks
belong in explicit manual validation procedures.

## Design boundaries

- Keep Core independent of concrete model vendors and model names.
- Add providers through existing abstractions and configuration, not branches
  in the Core facade.
- Keep routing as selection/decision logic; routers do not generate answers.
- Keep the bundled Web UI thin and dependent only on the public Core API.
- Do not add memory, tools, agents, voice, or autonomous behavior as incidental
  changes to infrastructure work.

See `AGENTS.md`, `docs/architecture/`, and `docs/adr/` before changing a public
contract or dependency direction.

## Pull requests

1. Keep each change focused and explain the user-visible or maintenance value.
2. Add or update the narrowest relevant tests.
3. Run targeted tests first, followed by the offline suite when warranted.
4. Update documentation only when behavior, interfaces, setup, or architecture
   changed.
5. Never commit credentials, `.env` files, model weights, virtual environments,
   logs, caches, or generated runtime output.

Bug reports and pull requests should include the Windows version, Python
version, profile used, exact command, expected behavior, and redacted failure
output. Do not paste API keys, prompts containing private data, or raw provider
payloads.

