[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Port,

    [switch]$InstallDeps,
    [switch]$Reset,
    [switch]$Watch
)

$ErrorActionPreference = 'Stop'

if (-not (Get-Command mpremote -ErrorAction SilentlyContinue)) {
    Write-Error "mpremote not found on PATH. Install with: pip install mpremote"
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$deviceRoot = Join-Path $repoRoot 'device'

if (-not (Test-Path $deviceRoot)) {
    Write-Error "device/ directory not found at $deviceRoot"
}

function Invoke-Mp {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Cmd)
    & mpremote connect $Port @Cmd
    if ($LASTEXITCODE -ne 0) { throw "mpremote $($Cmd -join ' ') failed" }
}

if ($InstallDeps) {
    Write-Host "Installing sdcard package via mip..." -ForegroundColor Cyan
    Invoke-Mp mip install sdcard
}

$skip = @('config.json', 'config.json.example')

$files = Get-ChildItem -Path $deviceRoot -Recurse -File | Where-Object {
    $skip -notcontains $_.Name
}

$rootPath = (Resolve-Path $deviceRoot).Path
$rootPrefixLen = $rootPath.Length + 1

function Get-RelPath {
    param([string]$Full)
    $rel = $Full.Substring($rootPrefixLen)
    return $rel -replace '\\', '/'
}

$dirs = $files | ForEach-Object {
    if ($_.DirectoryName.Length -le $rootPath.Length) { return $null }
    Get-RelPath $_.DirectoryName
} | Where-Object { $_ } | Select-Object -Unique | Sort-Object

$prevPref = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
foreach ($d in $dirs) {
    $remote = ":/$d"
    Write-Host "mkdir $remote" -ForegroundColor DarkGray
    & mpremote connect $Port mkdir $remote *> $null
}
$ErrorActionPreference = $prevPref

foreach ($f in $files) {
    $rel = Get-RelPath $f.FullName
    $remote = ":/$rel"
    Write-Host "cp $rel -> $remote" -ForegroundColor Gray
    Invoke-Mp cp $f.FullName $remote
}

Write-Host "Push complete." -ForegroundColor Green

if ($Reset) {
    Write-Host "Resetting device..." -ForegroundColor Cyan
    Invoke-Mp reset
}

if ($Watch) {
    Write-Host "Attaching to REPL (Ctrl-X to exit)..." -ForegroundColor Cyan
    & mpremote connect $Port repl
}
