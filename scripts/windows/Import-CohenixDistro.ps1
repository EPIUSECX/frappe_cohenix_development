#Requires -Version 5.1
<#
.SYNOPSIS
  Create an isolated Cohenix-Pilot WSL2 distro from Ubuntu 24.04.
.DESCRIPTION
  Prefers `wsl --install -d Ubuntu-24.04` into a dedicated name when supported,
  otherwise downloads the Ubuntu 24.04 rootfs and uses `wsl --import`.
  Refuses to overwrite an existing distro unless -Force is passed (explicit opt-in).
#>
[CmdletBinding()]
param(
  [string]$DistroName = "Cohenix-Pilot",
  [string]$InstallDir = "$env:LOCALAPPDATA\CohenixPilot\distro",
  [string]$RootfsUrl = "https://cloud-images.ubuntu.com/wsl/releases/24.04/current/ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz",
  [switch]$Force,
  [switch]$UseExistingUbuntu
)

$ErrorActionPreference = "Stop"

function Assert-SafeName([string]$Name) {
  if ($Name -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$') {
    throw "Invalid distro name: $Name"
  }
}

Assert-SafeName $DistroName

$result = [ordered]@{
  ok = $false
  distro = $DistroName
  created = $false
  reused = $false
  message = ""
}

$existing = & wsl.exe -l -q 2>$null
$names = @()
if ($existing) {
  $names = $existing | ForEach-Object { ($_ -replace "`0", "").Trim() } | Where-Object { $_ }
}

if ($names -contains $DistroName) {
  if (-not $Force) {
    $result.ok = $true
    $result.reused = $true
    $result.message = "Distro $DistroName already exists; leaving it unchanged."
    $result | ConvertTo-Json -Compress
    exit 0
  }
  throw "Refusing to destroy distro $DistroName. Unregister must be an explicit Settings action, not import -Force."
}

if ($UseExistingUbuntu) {
  $ubuntu = $names | Where-Object { $_ -match 'Ubuntu-24\.04|Ubuntu' } | Select-Object -First 1
  if (-not $ubuntu) {
    throw "No existing Ubuntu distro found for opt-in reuse."
  }
  $result.ok = $true
  $result.reused = $true
  $result.distro = $ubuntu
  $result.message = "Opt-in: using existing distro $ubuntu. Cohenix will not modify other distros."
  $result | ConvertTo-Json -Compress
  exit 0
}

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$rootfs = Join-Path $InstallDir "ubuntu-24.04.rootfs.tar.gz"

if (-not (Test-Path $rootfs)) {
  Write-Host "Downloading Ubuntu 24.04 WSL rootfs..."
  Invoke-WebRequest -Uri $RootfsUrl -OutFile $rootfs -UseBasicParsing
}

$vhdxDir = Join-Path $InstallDir $DistroName
New-Item -ItemType Directory -Force -Path $vhdxDir | Out-Null

Write-Host "Importing distro $DistroName (WSL2)..."
& wsl.exe --import $DistroName $vhdxDir $rootfs --version 2
if ($LASTEXITCODE -ne 0) {
  throw "wsl --import failed with exit $LASTEXITCODE"
}

# Best-effort: set default user after configure-distro runs inside the guest.
$result.ok = $true
$result.created = $true
$result.message = "Imported $DistroName from Ubuntu 24.04 rootfs."
$result | ConvertTo-Json -Compress
