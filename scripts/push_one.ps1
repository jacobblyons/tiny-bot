# Push a single file via `mpremote run`. Works around an mpremote 1.28 cp
# bug where the first-create cp into a freshly-mkdir'd directory fails
# with OSError: No such file/directory.
#
# Usage:
#   ./scripts/push_one.ps1 -Port COM9 -Local device/foo.py -Remote /foo.py

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Port,
    [Parameter(Mandatory=$true)][string]$Local,
    [Parameter(Mandatory=$true)][string]$Remote
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $Local)) { Write-Error "local file not found: $Local" }

$bytes = [System.IO.File]::ReadAllBytes((Resolve-Path $Local))
$b64 = [Convert]::ToBase64String($bytes)
$localSize = $bytes.Length

# Build a tiny on-device script. We split the b64 string so each line stays
# short — paste mode is happier with reasonable line lengths.
$chunkSize = 200
$lines = @()
for ($i = 0; $i -lt $b64.Length; $i += $chunkSize) {
    $end = [Math]::Min($chunkSize, $b64.Length - $i)
    $lines += "    '" + $b64.Substring($i, $end) + "',"
}
$tmp = [System.IO.Path]::GetTempFileName() + '.py'
@"
import binascii
parts = (
$($lines -join "`n")
)
data = binascii.a2b_base64(''.join(parts))
with open('$Remote', 'wb') as f:
    f.write(data)
import os
s = os.stat('$Remote')
print('WROTE', '$Remote', 'size', s[6])
"@ | Set-Content -Path $tmp -Encoding ASCII

try {
    & mpremote connect $Port run $tmp
    if ($LASTEXITCODE -ne 0) { throw "mpremote run failed" }
} finally {
    Remove-Item $tmp -ErrorAction SilentlyContinue
}

# Verify size matches — the memory note about silent corruption demands this.
$onDeviceSize = (& mpremote connect $Port exec "import os; print(os.stat('$Remote')[6])" | Select-Object -Last 1).Trim()
if ([int]$onDeviceSize -ne [int]$localSize) {
    Write-Error "size mismatch on $Remote local=$localSize device=$onDeviceSize"
} else {
    Write-Host "OK $Remote ($localSize bytes)" -ForegroundColor Green
}
