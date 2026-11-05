#Requires -Version 5.1
<#
.SYNOPSIS
  Windows preflight checks for Cohenix Pilot (read-only).
.DESCRIPTION
  Emits JSON suitable for the Tauri host. Does not enable features or reboot.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

function Test-IsAdmin {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  $p = New-Object Security.Principal.WindowsPrincipal($id)
  return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-WslStatus {
  $result = @{
    installed = $false
    version = $null
    defaultVersion = $null
    distros = @()
    rawError = $null
  }
  try {
    $wsl = Get-Command wsl.exe -ErrorAction Stop
    $result.installed = $true
    $list = & wsl.exe -l -v 2>&1 | Out-String
    $result.rawList = $list
    $ver = & wsl.exe --version 2>&1 | Out-String
    $result.version = ($ver -split "`n" | Select-Object -First 1).Trim()
    foreach ($line in ($list -split "`n")) {
      if ($line -match '^\s*(\*?)\s*(\S+)\s+(\w+)\s+(\d+)') {
        $result.distros += @{
          name = $Matches[2]
          state = $Matches[3]
          version = [int]$Matches[4]
          default = ($Matches[1] -eq "*")
        }
      }
    }
  } catch {
    $result.rawError = $_.Exception.Message
  }
  return $result
}

function Test-WebView2 {
  $keys = @(
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F301702D-A7A6-4586-8D2D-1C8B6B4E8C8A}",
    "HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F301702D-A7A6-4586-8D2D-1C8B6B4E8C8A}"
  )
  foreach ($k in $keys) {
    if (Test-Path $k) { return $true }
  }
  return $false
}

function Test-PortFree([int]$Port) {
  try {
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return -not $listener
  } catch {
    return $true
  }
}

$os = Get-CimInstance Win32_OperatingSystem
$cs = Get-CimInstance Win32_ComputerSystem
$disk = Get-PSDrive -Name C

$report = [ordered]@{
  ok = $true
  os = @{
    caption = $os.Caption
    version = $os.Version
    build = $os.BuildNumber
    arch = $env:PROCESSOR_ARCHITECTURE
  }
  admin = Test-IsAdmin
  ramGb = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
  diskFreeGb = [math]::Round($disk.Free / 1GB, 1)
  webView2 = Test-WebView2
  virtualization = $null
  wsl = Get-WslStatus
  ports = @{
    8000 = Test-PortFree 8000
    8002 = Test-PortFree 8002
    9000 = Test-PortFree 9000
  }
  remediation = @()
}

try {
  $hv = Get-CimInstance -ClassName Win32_ComputerSystem | Select-Object -ExpandProperty HypervisorPresent
  $report.virtualization = [bool]$hv
} catch {
  $report.virtualization = $null
}

if ($report.os.arch -ne "AMD64") {
  $report.ok = $false
  $report.remediation += "Cohenix Pilot requires Windows x64 (AMD64)."
}
if ($report.ramGb -lt 8) {
  $report.ok = $false
  $report.remediation += "At least 8 GB RAM is required (16 GB recommended)."
}
if ($report.diskFreeGb -lt 20) {
  $report.ok = $false
  $report.remediation += "Free at least 20 GB on the system drive."
}
if (-not $report.webView2) {
  $report.remediation += "Install Microsoft Edge WebView2 Runtime."
}
if (-not $report.wsl.installed) {
  $report.remediation += "WSL is not installed. The wizard can enable it with your permission."
}
foreach ($p in $report.ports.GetEnumerator()) {
  if (-not $p.Value) {
    $report.remediation += "Port $($p.Key) is in use. Stop the other process or change ports in Settings."
  }
}

$report | ConvertTo-Json -Depth 6 -Compress
