"""Static contracts for the opt-in LiteLLM Gateway environment setup."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "setup_oratrice.ps1"
GATEWAY_REQUIREMENTS = ROOT / "requirements-gateway.txt"


def _source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_gateway_uses_an_opt_in_environment_and_unconstrained_requirements() -> None:
    source = _source()

    assert re.search(r"\[switch\]\$Gateway\b", source)
    assert '$DefaultVenvName = ".venv"' in source
    assert '$DefaultVenvName = ".gateway-venv"' in source
    assert 'ChildPath "requirements-gateway.txt"' in source
    assert "$ConstraintsPath = $null" in source
    assert (
        '$RequirementsPath = Join-Path -Path $ProjectRoot -ChildPath "requirements.txt"'
        in source
    )
    assert (
        '$ConstraintsPath = Join-Path -Path $ProjectRoot -ChildPath "constraints.txt"'
        in source
    )

    # Core retains its constraints command; Gateway installs only its own
    # requirements file and never inherits the Core constraint set.
    assert "& $venvPython -m pip install -r $RequirementsPath 2>&1" in source
    assert (
        "& $venvPython -m pip install -r $RequirementsPath -c $ConstraintsPath 2>&1"
        in source
    )


def test_gateway_extra_is_parsed_as_a_base_distribution_and_exact_pin() -> None:
    source = _source()
    requirements = GATEWAY_REQUIREMENTS.read_text(encoding="utf-8")

    pattern_literal = next(
        line.strip()
        for line in source.splitlines()
        if line.strip().startswith("'^(?<name>")
    )
    assert pattern_literal.endswith("'")
    # Translate PowerShell/.NET named groups to Python syntax to exercise the
    # same expression without invoking the bootstrap or installing packages.
    pattern = re.sub(r"\(\?<([A-Za-z]+)>", r"(?P<\1>", pattern_literal[1:-1])
    parsed = re.match(pattern, "litellm[proxy, vision]==1.74.3")
    assert parsed is not None
    assert parsed.group("name") == "litellm"
    assert parsed.group("extras") == "[proxy, vision]"
    assert parsed.group("spec") == "==1.74.3"

    assert 'Name = $match.Groups["name"].Value' in source
    assert 'Extras = $match.Groups["extras"].Value' in source
    assert 'Get-ImportName -DistributionName $name' in source
    assert "importlib.import_module('$module')" in source
    assert "metadata.version('$name')" in source
    assert 'if ($operator -eq "==")' in source
    assert "[System.StringComparison]::Ordinal" in source

    gateway_entries = [
        line.split("#", 1)[0].strip()
        for line in requirements.splitlines()
        if line.split("#", 1)[0].strip().lower().startswith("litellm")
    ]
    assert len(gateway_entries) == 1
    assert re.fullmatch(r"litellm\[proxy\]\s*==\s*1\.74\.3", gateway_entries[0], re.I)


def test_check_only_stays_pip_free_and_normal_setup_runs_pip_check() -> None:
    source = _source()
    check_only_start = source.index("if ($CheckOnly) {")
    check_only_end = source.index("if (-not $Gateway -and", check_only_start)
    check_only_block = source[check_only_start:check_only_end]

    assert "-m pip" not in check_only_block
    install_position = source.index("-m pip install -r $RequirementsPath")
    check_position = source.index("-m pip check", install_position)
    package_position = source.index(
        "Test-RequiredPackages -Interpreter $venvPython", check_position
    )
    assert install_position < check_position < package_position


def test_litellm_import_uses_local_cost_map_only_in_child_process() -> None:
    source = _source()
    branch_position = source.index('if ($name -ieq "litellm")')
    local_map_position = source.index(
        "os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'", branch_position
    )
    import_position = source.index(
        "importlib.import_module('$module')", local_map_position
    )

    assert branch_position < local_map_position < import_position
    assert "$env:LITELLM_LOCAL_MODEL_COST_MAP" not in source
