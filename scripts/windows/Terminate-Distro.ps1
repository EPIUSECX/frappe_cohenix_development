#Requires -Version 5.1
param(
  [Parameter(Mandatory = $true)][string]$DistroName
)

if ($DistroName -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$') {
  throw "Invalid distro name"
}

& wsl.exe --terminate $DistroName 2>&1 | Out-String | Write-Output
exit 0
