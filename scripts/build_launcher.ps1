[CmdletBinding()]
param(
    [string]$OutputPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$source = Join-Path $repoRoot "launcher\windows\Start-Oratrice.cs"
if ([String]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $repoRoot "work\m9-native\Start-Oratrice.m9.exe"
} else {
    if (-not [IO.Path]::IsPathRooted($OutputPath)) {
        $OutputPath = Join-Path $repoRoot $OutputPath
    }
    $OutputPath = [IO.Path]::GetFullPath($OutputPath)
}

if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    throw "Launcher source does not exist: $source"
}

$compilerCandidates = @(
    (Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"),
    (Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe")
)
$compiler = $compilerCandidates |
    Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
    Select-Object -First 1
if ([String]::IsNullOrWhiteSpace($compiler)) {
    $command = Get-Command csc.exe -CommandType Application -ErrorAction SilentlyContinue
    if ($null -ne $command) { $compiler = $command.Source }
}
if ([String]::IsNullOrWhiteSpace($compiler)) {
    throw "Could not find the .NET Framework C# compiler (csc.exe)."
}

$outputDirectory = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
& $compiler /nologo /target:exe /optimize+ "/out:$OutputPath" $source
if ($LASTEXITCODE -ne 0) {
    throw "csc.exe failed with exit code $LASTEXITCODE."
}

$hash = Get-FileHash -LiteralPath $OutputPath -Algorithm SHA256
Write-Output "compiler=$compiler"
Write-Output "output=$OutputPath"
Write-Output "sha256=$($hash.Hash)"
