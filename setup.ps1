[CmdletBinding()]
param(
    [ValidateSet(1, 2, 3, 4, 5)]
    [int[]]$Course = @(1, 2, 3, 4, 5),
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uvCommand) {
    $uvCandidate = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
    if (Test-Path -LiteralPath $uvCandidate) {
        $uvPath = $uvCandidate
    } else {
        Write-Host 'Installing uv 0.11.24 from astral.sh...'
        Invoke-RestMethod 'https://astral.sh/uv/0.11.24/install.ps1' | Invoke-Expression
        if (-not (Test-Path -LiteralPath $uvCandidate)) {
            throw 'uv installation did not produce ~/.local/bin/uv.exe. Install uv and retry.'
        }
        $uvPath = $uvCandidate
    }
} else {
    $uvPath = $uvCommand.Source
}

$setupArgs = @('--uv', $uvPath, '--course') + @($Course | ForEach-Object { "$_" })
if ($CheckOnly) { $setupArgs += '--check-only' }
& $uvPath run --no-project --managed-python --python 3.10.20 (Join-Path $PSScriptRoot 'scripts/setup_envs.py') @setupArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
