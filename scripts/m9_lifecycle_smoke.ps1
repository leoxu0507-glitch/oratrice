[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherExe
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$candidateInput = [IO.Path]::GetFullPath($LauncherExe)
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$workRoot = Join-Path $repoRoot "work\m9-native-smoke"
$profile = Join-Path $workRoot "profile.yaml"
$surrogate = Join-Path $workRoot "surrogate-parent.ps1"
$parentPidFile = Join-Path $workRoot "parent.pid"
$childPidFile = Join-Path $workRoot "child.pid"
$launcherStdout = Join-Path $workRoot "launcher.stdout.log"
$launcherStderr = Join-Path $workRoot "launcher.stderr.log"
$shell = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
$stagedCandidate = Join-Path $repoRoot (".m9-native-candidate-" + [Guid]::NewGuid().ToString("N") + ".exe")
$candidate = $stagedCandidate

if (-not (Test-Path -LiteralPath $candidateInput -PathType Leaf)) {
    throw "Launcher executable does not exist: $candidateInput"
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project Python executable does not exist: $python"
}
New-Item -ItemType Directory -Force -Path $workRoot | Out-Null
Copy-Item -LiteralPath $candidateInput -Destination $stagedCandidate -Force

@'
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ParentPidFile,
    [Parameter(Mandatory = $true)][string]$ChildPidFile
)

$ErrorActionPreference = "Stop"
$shell = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
$child = Start-Process -FilePath $shell -ArgumentList @(
    "-NoProfile", "-NonInteractive", "-Command", "Start-Sleep -Seconds 600"
) -WindowStyle Hidden -PassThru
Set-Content -LiteralPath $ParentPidFile -Value $PID -Encoding UTF8
Set-Content -LiteralPath $ChildPidFile -Value $child.Id -Encoding UTF8
while ($true) { Start-Sleep -Seconds 1 }
'@ | Set-Content -LiteralPath $surrogate -Encoding UTF8

$workForward = $workRoot.Replace("\", "/")
$surrogateForward = $surrogate.Replace("\", "/")
$parentPidForward = $parentPidFile.Replace("\", "/")
$childPidForward = $childPidFile.Replace("\", "/")
@"
version: 1
runtimes:
  surrogate:
    id: runtime.surrogate
    name: M9 lifecycle surrogate
    type: executable
    executable: C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
    working_dir: $workForward
    args:
      - -NoProfile
      - -NonInteractive
      - -File
      - $surrogateForward
      - -ParentPidFile
      - $parentPidForward
      - -ChildPidFile
      - $childPidForward
defaults:
  launcher:
    targets:
      - id: core_api
        runtime: runtime.surrogate
        timeout: 10
    optional_targets: []
    ui_url: http://127.0.0.1:1/
    ui_health_url: http://127.0.0.1:1/
    open_ui_if_available: false
"@ | Set-Content -LiteralPath $profile -Encoding UTF8

function Get-RecordedPid([string]$path) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $null }
    $value = (Get-Content -LiteralPath $path -Raw).Trim()
    $pidValue = 0
    if (-not [int]::TryParse($value, [Globalization.NumberStyles]::Integer,
            [Globalization.CultureInfo]::InvariantCulture, [ref]$pidValue)) {
        throw "Invalid PID file: $path"
    }
    return $pidValue
}

function Test-PidGone([int]$pidValue) {
    if ($pidValue -le 0) { return $true }
    return $null -eq (Get-Process -Id $pidValue -ErrorAction SilentlyContinue)
}

function Stop-ExactPid([int]$pidValue) {
    if ($pidValue -gt 0 -and -not (Test-PidGone $pidValue)) {
        Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
    }
}

function Wait-File([string]$path, [int]$seconds = 15) {
    $deadline = [DateTime]::UtcNow.AddSeconds($seconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Test-Path -LiteralPath $path -PathType Leaf) { return }
        Start-Sleep -Milliseconds 200
    }
    throw "Timed out waiting for $path"
}

function Wait-Gone([int[]]$pids, [int]$seconds = 10) {
    $deadline = [DateTime]::UtcNow.AddSeconds($seconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (@($pids | Where-Object { -not (Test-PidGone $_) }).Count -eq 0) { return $true }
        Start-Sleep -Milliseconds 200
    }
    return @($pids | Where-Object { -not (Test-PidGone $_) }).Count -eq 0
}

$previousPython = [Environment]::GetEnvironmentVariable("ORATRICE_PYTHON", "Process")
$candidateProcess = $null
$externalProcess = $null
$externalPid = 0
$allObserved = [Collections.Generic.List[int]]::new()
try {
    [Environment]::SetEnvironmentVariable("ORATRICE_PYTHON", $python, "Process")
    $externalProcess = Start-Process -FilePath $shell -ArgumentList @(
        "-NoProfile", "-NonInteractive", "-Command", "Start-Sleep -Seconds 600"
    ) -WindowStyle Hidden -PassThru
    $externalPid = $externalProcess.Id
    Remove-Item -LiteralPath $parentPidFile, $childPidFile -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $launcherStdout, $launcherStderr -Force -ErrorAction SilentlyContinue

    $candidateProcess = Start-Process -FilePath $candidate -ArgumentList @(
        "--profile", $profile, "--no-browser"
    ) -WindowStyle Hidden -PassThru -RedirectStandardOutput $launcherStdout -RedirectStandardError $launcherStderr
    Wait-File $parentPidFile
    Wait-File $childPidFile
    $parentPid = Get-RecordedPid $parentPidFile
    $childPid = Get-RecordedPid $childPidFile
    $allObserved.Add($candidateProcess.Id)
    $allObserved.Add($parentPid)
    $allObserved.Add($childPid)
    if ($candidateProcess.HasExited) { throw "Candidate exited before the surrogate became ready" }
    if ((Test-PidGone $parentPid) -or (Test-PidGone $childPid)) {
        throw "Surrogate process tree was not alive after launcher startup"
    }

    Stop-ExactPid $candidateProcess.Id
    if (-not (Wait-Gone @($candidateProcess.Id, $parentPid, $childPid))) {
        throw "Job-close cleanup did not reap the complete recorded process tree"
    }
    if (Test-PidGone $externalPid) {
        throw "External sibling exited during the first candidate cleanup"
    }
    Write-Output "forced_parent_exit=PASS candidate=$($candidateProcess.Id) parent=$parentPid child=$childPid"
    Write-Output "external_survivor_after_first=PASS pid=$externalPid"
    $candidateProcess = $null

    Remove-Item -LiteralPath $parentPidFile, $childPidFile -Force -ErrorAction SilentlyContinue
    $candidateProcess = Start-Process -FilePath $candidate -ArgumentList @(
        "--profile", $profile, "--no-browser"
    ) -WindowStyle Hidden -PassThru -RedirectStandardOutput $launcherStdout -RedirectStandardError $launcherStderr
    Wait-File $parentPidFile
    Wait-File $childPidFile
    $parentPid = Get-RecordedPid $parentPidFile
    $childPid = Get-RecordedPid $childPidFile
    $allObserved.Add($candidateProcess.Id)
    $allObserved.Add($parentPid)
    $allObserved.Add($childPid)
    if ($candidateProcess.HasExited) { throw "Candidate exited before the restart became ready" }
    if ((Test-PidGone $parentPid) -or (Test-PidGone $childPid)) {
        throw "Surrogate process tree was not alive after restart"
    }
    Stop-ExactPid $candidateProcess.Id
    if (-not (Wait-Gone @($candidateProcess.Id, $parentPid, $childPid))) {
        throw "Job-close cleanup did not reap the restarted process tree"
    }
    if (Test-PidGone $externalPid) {
        throw "External sibling exited during the second candidate cleanup"
    }
    Write-Output "restart_after_cleanup=PASS candidate=$($candidateProcess.Id) parent=$parentPid child=$childPid"
    Write-Output "external_survivor_after_second=PASS pid=$externalPid"
    $candidateProcess = $null
    Write-Output "profile=$profile"
    Write-Output "observed_pids=$($allObserved -join ',')"
} finally {
    if ($null -ne $candidateProcess) { Stop-ExactPid $candidateProcess.Id }
    foreach ($pidValue in @($allObserved | Select-Object -Unique)) { Stop-ExactPid $pidValue }
    if ($externalPid -gt 0) {
        Stop-ExactPid $externalPid
        if (-not (Wait-Gone @($externalPid))) {
            Write-Error "External sibling cleanup did not finish for exact PID $externalPid"
        }
    }
    if (Test-Path -LiteralPath $stagedCandidate -PathType Leaf) {
        Remove-Item -LiteralPath $stagedCandidate -Force -ErrorAction SilentlyContinue
    }
    [Environment]::SetEnvironmentVariable("ORATRICE_PYTHON", $previousPython, "Process")
}
