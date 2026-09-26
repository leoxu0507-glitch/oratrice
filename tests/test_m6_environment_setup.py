"""Static contracts for the Windows local-environment bootstrap.

These tests inspect the PowerShell source and, when Windows PowerShell is
available, ask its parser to parse the file.  They deliberately never invoke
the setup script, Python, pip, a virtual environment, or a network endpoint.
"""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "setup_oratrice.ps1"
REQUIREMENTS = ROOT / "requirements.txt"
CONSTRAINTS = ROOT / "constraints.txt"


def _source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_setup_script_declares_reproducible_selection_and_check_contract() -> None:
    source = _source()

    assert SCRIPT.is_file()
    assert re.search(r"\[string\]\$Python\b", source)
    assert re.search(r"\[string\]\$VenvPath\b", source)
    assert re.search(r"\[switch\]\$CheckOnly\b", source)

    # The order is part of the operator-visible selection explanation.
    assert source.index("Resolve-AbsolutePath -Path $ExplicitPython") < source.index(
        'GetEnvironmentVariable("ORATRICE_PYTHON")'
    )
    assert source.index('GetEnvironmentVariable("ORATRICE_PYTHON")') < source.index(
        'Get-Command -Name "py.exe"'
    )
    assert "-3 -c" in source
    assert "Python 3.10 or newer" in source

    # A missing venv is created only at the resolved default or explicit path;
    # CheckOnly must fail before creation and before pip.
    assert "Resolve-VenvPath" in source
    assert "New-OratriceVenv" in source
    assert 'if ($CheckOnly)' in source
    assert "-CheckOnly found no virtual environment" in source
    pip_call = "& $venvPython -m pip install -r $RequirementsPath"
    assert pip_call in source
    assert "-c $ConstraintsPath" in source
    assert "-m pip install -r requirements.txt -c constraints.txt" in source
    assert source.index('if ($CheckOnly)') < source.index(pip_call)
    assert "Test-RequiredPackages -Interpreter $venvPython" in source


def test_setup_script_uses_local_requirements_and_does_not_mutate_machine_state() -> None:
    source = _source()
    requirements = REQUIREMENTS.read_text(encoding="utf-8")
    constraints = CONSTRAINTS.read_text(encoding="utf-8")

    for package in ("PyYAML", "requests", "fastapi", "uvicorn", "pytest", "httpx"):
        assert re.search(rf"(?m)^\s*{re.escape(package)}(?:[<>=!~]|\s|$)", requirements)
    assert "$RequirementsPath = Join-Path -Path $ProjectRoot -ChildPath \"requirements.txt\"" in source
    assert "$ConstraintsPath = Join-Path -Path $ProjectRoot -ChildPath \"constraints.txt\"" in source
    assert "-r $RequirementsPath" in source
    assert "-c $ConstraintsPath" in source

    expected_constraints = {
        "PyYAML": "6.0.3",
        "requests": "2.34.2",
        "fastapi": "0.115.14",
        "uvicorn": "0.29.0",
        "pytest": "9.1.1",
        "httpx": "0.28.1",
    }
    assert "M6 verified direct-dependency baseline" in constraints
    parsed_constraints = {}
    for line in constraints.splitlines():
        match = re.match(r"^([A-Za-z0-9_.-]+)==([^#\s]+)$", line.strip())
        if match:
            parsed_constraints[match.group(1)] = match.group(2)
    assert parsed_constraints == expected_constraints

    forbidden = (
        "Set-ExecutionPolicy",
        "SetEnvironmentVariable(",
        "[Environment]::SetEnvironmentVariable",
        "New-ItemProperty",
        "reg.exe",
        "Invoke-WebRequest",
        "Start-BitsTransfer",
        "curl.exe",
        "wget.exe",
        "$env:PATH =",
        "$env:Path =",
        "Remove-Item",
    )
    for token in forbidden:
        assert token not in source

    # No credentials are generated or written by the setup path.
    assert "ORATRICE_LITELLM_MASTER_KEY" not in source
    assert "DEEPSEEK_API_KEY" not in source
    assert "Get-Random" not in source


def test_windows_powershell_parser_accepts_setup_script() -> None:
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("Windows PowerShell is not available for parser-only validation")

    # ParseFile builds an AST and never runs the script.  Quote the path as a
    # PowerShell single-quoted literal; this test does not pass user data to
    # the script or invoke pip/network operations.
    path_literal = str(SCRIPT).replace("'", "''")
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{path_literal}',[ref]$tokens,[ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { $_.ToString() }; exit 1 }"
    )
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
