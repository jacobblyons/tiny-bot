[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Drive,

    [switch]$DryRun,
    [switch]$IncludeLib
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path "${Drive}\boot_out.txt")) {
    Write-Warning "${Drive}\boot_out.txt not found — verify this is the CIRCUITPY drive."
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$deviceRoot = Join-Path $repoRoot 'device'

$skipNames = @('config.json', 'config.json.example', '.bootstrap_key', '.bootstrap_wifi')

$files = Get-ChildItem -Path $deviceRoot -Recurse -File | Where-Object {
    $skipNames -notcontains $_.Name -and
    ($IncludeLib -or $_.FullName -notmatch '\\lib\\')
}

$rootPath = (Resolve-Path $deviceRoot).Path
$rootPrefixLen = $rootPath.Length + 1

foreach ($f in $files) {
    $rel = $f.FullName.Substring($rootPrefixLen)
    $dst = Join-Path $Drive $rel
    $dstDir = Split-Path $dst -Parent
    if (-not (Test-Path $dstDir)) {
        if ($DryRun) { Write-Host "mkdir $dstDir" -ForegroundColor DarkGray }
        else { New-Item -ItemType Directory -Force -Path $dstDir | Out-Null }
    }
    if ($DryRun) {
        Write-Host "cp $rel -> $dst" -ForegroundColor Gray
    } else {
        Copy-Item -Path $f.FullName -Destination $dst -Force
        Write-Host "cp $rel" -ForegroundColor Gray
    }
}

if (-not $DryRun) {
    Write-Host "Push complete. Eject ${Drive}: in Explorer to flush, then the board will auto-reload." -ForegroundColor Green
}
