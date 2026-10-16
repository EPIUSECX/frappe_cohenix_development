#Requires -Version 5.1
<#
.SYNOPSIS
  Enable WSL2 using documented Microsoft wsl.exe commands.
.NOTES
  Requests elevation only when needed. Never forces a restart; returns
  restartRequired=true so the desktop app can ask the user.
#>
[CmdletBinding()]
param(
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Test-IsAdmin {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  $p = New-Object Security.Principal.WindowsPrincipal($id)
  return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

$result = [ordered]@{
  ok = $false
  restartRequired = $false
  actions = @()
  message = ""
}

if ($DryRun) {
  $result.ok = $true
  $result.message = "Dry run only; no changes made."
  $result | ConvertTo-Json -Compress
  exit 0
}

if (-not (Test-IsAdmin)) {
  $result.message = "Administrator approval is required to enable WSL."
  $result.actions += "relaunch_elevated"
  $result | ConvertTo-Json -Compress
  exit 2
}

try {
  # Documented path: wsl --install enables components and may require reboot.
  $output = & wsl.exe --install --no-distribution 2>&1 | Out-String
  $result.actions += "wsl --install --no-distribution"
  $result.message = $output.Trim()
  if ($output -match "(?i)restart|reboot") {
    $result.restartRequired = $true
  }
  # Prefer WSL2 as default when the command exists.
  try {
    & wsl.exe --set-default-version 2 2>&1 | Out-Null
    $result.actions += "wsl --set-default-version 2"
  } catch {
    # Older builds may not support this yet before reboot.
  }
  $result.ok = $true
} catch {
  $result.message = $_.Exception.Message
  $result.ok = $false
}

$result | ConvertTo-Json -Compress
if (-not $result.ok) { exit 1 }
if ($result.restartRequired) { exit 3 }
exit 0
