[CmdletBinding()]
param(
    # An absolute interpreter path selected by the caller.  This takes
    # precedence over ORATRICE_PYTHON and the py launcher.
    [string]$Python,

    # The default is <project root>\.venv.  Relative values are interpreted
    # relative to the project root; absolute values are accepted only when
    # explicitly supplied by the caller.
    [string]$VenvPath,

    # Inspect the selected interpreter, venv, and requirements without making
    # a venv, invoking pip, or changing machine/user configuration.
    [switch]$CheckOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path -Path $PSScriptRoot -ChildPath ".."))
$RequirementsPath = Join-Path -Path $ProjectRoot -ChildPath "requirements.txt"
$ConstraintsPath = Join-Path -Path $ProjectRoot -ChildPath "constraints.txt"

function Format-NativeFailure {
    param([object[]]$Output)

    $lines = @(
        $Output |
            ForEach-Object { if ($null -ne $_) { ([string]$_).Trim() } } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    if ($lines.Count -eq 0) {
        return "no diagnostic output"
    }
    # Keep diagnostics useful without echoing an entire traceback or any
    # environment-derived value that a third-party tool might include.
    $first = [string]$lines[0]
    if ($first.Length -gt 240) {
        return $first.Substring(0, 240)
    }
    return $first
}

function Resolve-AbsolutePath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Description
    )

    $candidate = $Path.Trim()
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        throw "$Description is empty."
    }
    if (-not [System.IO.Path]::IsPathRooted($candidate)) {
        throw "$Description must be an absolute path: '$candidate'."
    }
    try {
        return [System.IO.Path]::GetFullPath($candidate)
    }
    catch {
        throw "$Description is not a valid path."
    }
}

function Resolve-PythonPath {
    param([string]$ExplicitPython)

    if (-not [string]::IsNullOrWhiteSpace($ExplicitPython)) {
        $path = Resolve-AbsolutePath -Path $ExplicitPython -Description "-Python"
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "-Python does not point to an existing interpreter: '$path'."
        }
        return [pscustomobject]@{ Path = $path; Source = "-Python" }
    }

    $configuredPython = [Environment]::GetEnvironmentVariable("ORATRICE_PYTHON")
    if (-not [string]::IsNullOrWhiteSpace($configuredPython)) {
        $path = Resolve-AbsolutePath -Path $configuredPython -Description "ORATRICE_PYTHON"
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "ORATRICE_PYTHON does not point to an existing interpreter: '$path'."
        }
        return [pscustomobject]@{ Path = $path; Source = "ORATRICE_PYTHON" }
    }

    $pyCommand = Get-Command -Name "py.exe" -CommandType Application -ErrorAction SilentlyContinue
    if ($null -eq $pyCommand) {
        throw "No Python interpreter selected. Pass -Python <absolute path>, set ORATRICE_PYTHON, or install py.exe with a Python 3 installation."
    }

    # Ask the Windows launcher for its available Python 3 interpreter.  This
    # does not install a runtime and leaves PATH, registry, and policy intact.
    $probeOutput = @(& $pyCommand.Source -3 -c "import sys; print(sys.executable)" 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "py.exe could not select a Python 3 interpreter: $(Format-NativeFailure -Output $probeOutput)"
    }
    $lines = @(
        $probeOutput |
            ForEach-Object { if ($null -ne $_) { ([string]$_).Trim().Trim('"') } } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    if ($lines.Count -eq 0) {
        throw "py.exe did not report a Python 3 interpreter. Install Python 3 or pass -Python <absolute path>."
    }
    $path = Resolve-AbsolutePath -Path ([string]$lines[$lines.Count - 1]) -Description "py.exe interpreter"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "py.exe reported an interpreter that does not exist: '$path'."
    }
    return [pscustomobject]@{ Path = $path; Source = "py.exe -3" }
}

function Get-PythonVersion {
    param(
        [Parameter(Mandatory = $true)][string]$Interpreter,
        [Parameter(Mandatory = $true)][string]$Description
    )

    $output = @(
        & $Interpreter -c "import sys; print('%d.%d.%d' % sys.version_info[:3])" 2>&1
    )
    if ($LASTEXITCODE -ne 0) {
        throw "$Description could not run '$Interpreter': $(Format-NativeFailure -Output $output)"
    }
    $versionText = @(
        $output |
            ForEach-Object { if ($null -ne $_) { ([string]$_).Trim() } } |
            Where-Object { $_ -match '^\d+\.\d+\.\d+$' }
    )
    if ($versionText.Count -eq 0) {
        throw "$Description returned no usable Python version."
    }
    $version = [version]$versionText[$versionText.Count - 1]
    if ($version.Major -ne 3 -or $version -lt ([version]"3.10.0")) {
        throw "$Description must be Python 3.10 or newer; found $version."
    }
    return $version
}

function Resolve-VenvPath {
    param([string]$ExplicitVenvPath)

    if ([string]::IsNullOrWhiteSpace($ExplicitVenvPath)) {
        return [System.IO.Path]::GetFullPath((Join-Path -Path $ProjectRoot -ChildPath ".venv"))
    }
    $candidate = $ExplicitVenvPath.Trim()
    if ([System.IO.Path]::IsPathRooted($candidate)) {
        return Resolve-AbsolutePath -Path $candidate -Description "-VenvPath"
    }
    try {
        return [System.IO.Path]::GetFullPath((Join-Path -Path $ProjectRoot -ChildPath $candidate))
    }
    catch {
        throw "-VenvPath is not a valid path: '$candidate'."
    }
}

function Get-VenvPythonPath {
    param([Parameter(Mandatory = $true)][string]$ResolvedVenvPath)

    if (Test-Path -LiteralPath $ResolvedVenvPath -PathType Leaf) {
        throw "Virtual-environment path is a file, not a directory: '$ResolvedVenvPath'."
    }
    $configuration = Join-Path -Path $ResolvedVenvPath -ChildPath "pyvenv.cfg"
    $venvPython = Join-Path -Path $ResolvedVenvPath -ChildPath "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $configuration -PathType Leaf) -or
        -not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        throw "Virtual environment is missing or incomplete at '$ResolvedVenvPath'. Run this script without -CheckOnly to create it, or choose another -VenvPath."
    }
    return $venvPython
}

function New-OratriceVenv {
    param(
        [Parameter(Mandatory = $true)][string]$BaseInterpreter,
        [Parameter(Mandatory = $true)][string]$ResolvedVenvPath,
        [Parameter(Mandatory = $true)][string]$InterpreterSource
    )

    if (Test-Path -LiteralPath $ResolvedVenvPath -PathType Leaf) {
        throw "Cannot create a virtual environment because the target is a file: '$ResolvedVenvPath'."
    }
    $parent = Split-Path -Parent $ResolvedVenvPath
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        throw "The parent directory for -VenvPath does not exist: '$parent'. Create it explicitly, then retry."
    }
    Write-Host "Creating virtual environment at $ResolvedVenvPath using $InterpreterSource ($BaseInterpreter)."
    $output = @(& $BaseInterpreter -m venv $ResolvedVenvPath 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Python venv creation failed at '$ResolvedVenvPath': $(Format-NativeFailure -Output $output)"
    }
}

function Get-RequirementEntries {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Requirements file was not found: '$Path'."
    }
    $entries = @()
    foreach ($rawLine in (Get-Content -LiteralPath $Path -Encoding UTF8)) {
        $line = ([string]$rawLine -split '#', 2)[0].Trim()
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        if ($line.StartsWith("-")) {
            throw "Unsupported requirements option '$line'. Keep setup requirements as package entries."
        }
        $match = [regex]::Match(
            $line,
            '^(?<name>[A-Za-z0-9_.-]+)\s*(?<spec>(?:[<>=!~]=?\s*[^,;\s]+(?:\s*,\s*[<>=!~]=?\s*[^,;\s]+)*)?)\s*(?:;.*)?$'
        )
        if (-not $match.Success) {
            throw "Could not parse requirements entry '$line'."
        }
        $entries += [pscustomobject]@{
            Name = $match.Groups["name"].Value
            Spec = $match.Groups["spec"].Value.Trim()
        }
    }
    if ($entries.Count -eq 0) {
        throw "Requirements file contains no package entries: '$Path'."
    }
    return $entries
}

function Convert-VersionParts {
    param([Parameter(Mandatory = $true)][string]$Value)

    $match = [regex]::Match($Value.Trim(), '^(?<major>\d+)(?:\.(?<minor>\d+))?(?:\.(?<patch>\d+))?')
    if (-not $match.Success) {
        throw "Package reported an invalid version '$Value'."
    }
    return @(
        [int]$match.Groups["major"].Value,
        [int]$(if ($match.Groups["minor"].Success) { $match.Groups["minor"].Value } else { 0 }),
        [int]$(if ($match.Groups["patch"].Success) { $match.Groups["patch"].Value } else { 0 })
    )
}

function Compare-VersionParts {
    param(
        [Parameter(Mandatory = $true)][int[]]$Left,
        [Parameter(Mandatory = $true)][int[]]$Right
    )

    for ($index = 0; $index -lt 3; $index++) {
        if ($Left[$index] -lt $Right[$index]) { return -1 }
        if ($Left[$index] -gt $Right[$index]) { return 1 }
    }
    return 0
}

function Test-VersionSpec {
    param(
        [Parameter(Mandatory = $true)][string]$Version,
        [string]$Spec
    )

    if ([string]::IsNullOrWhiteSpace($Spec)) {
        return $true
    }
    $actual = Convert-VersionParts -Value $Version
    foreach ($condition in ($Spec -split ',')) {
        $match = [regex]::Match($condition.Trim(), '^(?<operator><=|>=|==|!=|<|>)\s*(?<version>[^\s]+)$')
        if (-not $match.Success) {
            throw "Unsupported version constraint '$condition'."
        }
        $expected = Convert-VersionParts -Value $match.Groups["version"].Value
        $comparison = Compare-VersionParts -Left $actual -Right $expected
        $operator = $match.Groups["operator"].Value
        $satisfied = switch ($operator) {
            ">=" { $comparison -ge 0; break }
            "<=" { $comparison -le 0; break }
            "==" { $comparison -eq 0; break }
            "!=" { $comparison -ne 0; break }
            ">" { $comparison -gt 0; break }
            "<" { $comparison -lt 0; break }
            default { $false }
        }
        if (-not $satisfied) {
            return $false
        }
    }
    return $true
}

function Get-ImportName {
    param([Parameter(Mandatory = $true)][string]$DistributionName)

    $normalised = $DistributionName.ToLowerInvariant().Replace("_", "-")
    $known = @{
        "pyyaml" = "yaml"
        "requests" = "requests"
        "fastapi" = "fastapi"
        "uvicorn" = "uvicorn"
        "pytest" = "pytest"
        "httpx" = "httpx"
    }
    if ($known.ContainsKey($normalised)) {
        return $known[$normalised]
    }
    return $normalised.Replace("-", "_")
}

function Test-RequiredPackages {
    param(
        [Parameter(Mandatory = $true)][string]$Interpreter,
        [Parameter(Mandatory = $true)][object[]]$Requirements
    )

    $failures = @()
    foreach ($requirement in $Requirements) {
        $name = [string]$requirement.Name
        $spec = [string]$requirement.Spec
        $module = Get-ImportName -DistributionName $name
        $code = "import importlib, importlib.metadata as metadata; importlib.import_module('$module'); print(metadata.version('$name'))"
        $output = @(& $Interpreter -c $code 2>&1)
        if ($LASTEXITCODE -ne 0) {
            $failures += "$name is missing or cannot be imported"
            continue
        }
        $versions = @(
            $output |
                ForEach-Object { if ($null -ne $_) { ([string]$_).Trim() } } |
                Where-Object { $_ -match '^\d+(?:\.\d+){0,3}(?:[-+].*)?$' }
        )
        if ($versions.Count -eq 0) {
            $failures += "$name reported no usable version"
            continue
        }
        $version = [string]$versions[$versions.Count - 1]
        if (-not (Test-VersionSpec -Version $version -Spec $spec)) {
            $displaySpec = if ([string]::IsNullOrWhiteSpace($spec)) { "(any version)" } else { $spec }
            $failures += "$name $version does not satisfy $displaySpec"
            continue
        }
        Write-Host ("  PASS {0} {1}" -f $name, $version)
    }
    if ($failures.Count -gt 0) {
        throw ("Required packages are not ready: " + ($failures -join "; "))
    }
}

try {
    $basePython = Resolve-PythonPath -ExplicitPython $Python
    $baseVersion = Get-PythonVersion -Interpreter $basePython.Path -Description "Selected interpreter"
    $resolvedVenvPath = Resolve-VenvPath -ExplicitVenvPath $VenvPath
    $requirements = Get-RequirementEntries -Path $RequirementsPath

    Write-Host ("Selected Python: {0} ({1}, Python {2})" -f $basePython.Path, $basePython.Source, $baseVersion)
    Write-Host ("Project root: {0}" -f $ProjectRoot)
    Write-Host ("Virtual environment: {0}" -f $resolvedVenvPath)
    Write-Host ("Requirements: {0} package entries from {1}" -f $requirements.Count, $RequirementsPath)

    $venvConfiguration = Join-Path -Path $resolvedVenvPath -ChildPath "pyvenv.cfg"
    $venvPython = Join-Path -Path $resolvedVenvPath -ChildPath "Scripts\python.exe"
    $venvExists = (Test-Path -LiteralPath $venvConfiguration -PathType Leaf) -or
        (Test-Path -LiteralPath $venvPython -PathType Leaf)

    if ($CheckOnly) {
        if (-not $venvExists) {
            throw "-CheckOnly found no virtual environment at '$resolvedVenvPath'. Run without -CheckOnly to create it."
        }
        $venvPython = Get-VenvPythonPath -ResolvedVenvPath $resolvedVenvPath
        $venvVersion = Get-PythonVersion -Interpreter $venvPython -Description "Virtual-environment interpreter"
        Write-Host ("Virtual-environment Python: {0} (Python {1})" -f $venvPython, $venvVersion)
        Write-Host "Checking required imports and versions (no pip or network access)."
        Test-RequiredPackages -Interpreter $venvPython -Requirements $requirements
        Write-Host "CheckOnly passed. No files, environment variables, PATH entries, registry values, or execution policy were changed."
        exit 0
    }

    if (-not $CheckOnly -and -not (Test-Path -LiteralPath $ConstraintsPath -PathType Leaf)) {
        throw "Constraints file was not found: '$ConstraintsPath'. Restore it before installing."
    }

    if (-not $venvExists) {
        New-OratriceVenv -BaseInterpreter $basePython.Path -ResolvedVenvPath $resolvedVenvPath -InterpreterSource $basePython.Source
    }
    $venvPython = Get-VenvPythonPath -ResolvedVenvPath $resolvedVenvPath
    $venvVersion = Get-PythonVersion -Interpreter $venvPython -Description "Virtual-environment interpreter"
    Write-Host ("Virtual-environment Python: {0} (Python {1})" -f $venvPython, $venvVersion)

    # The selected venv interpreter owns dependency installation.  The
    # operator-visible command is: <venv>\Scripts\python.exe -m pip install -r requirements.txt -c constraints.txt.
    # No global pip, PATH mutation, execution-policy change, or secret generation occurs.
    Write-Host "Installing requirements with the selected virtual-environment interpreter."
    $pipOutput = @(& $venvPython -m pip install -r $RequirementsPath -c $ConstraintsPath 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed: $(Format-NativeFailure -Output $pipOutput)"
    }
    Write-Host "Dependency installation completed. Checking required imports and versions."
    Test-RequiredPackages -Interpreter $venvPython -Requirements $requirements
    Write-Host "Oratrice environment is ready. Use $venvPython for tests and launcher commands."
    exit 0
}
catch {
    Write-Error ("Oratrice environment setup failed: " + $_.Exception.Message)
    exit 1
}
