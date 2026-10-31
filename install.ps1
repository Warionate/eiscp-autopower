# Set up eiscp-autopower and register it to start at logon for the current user.
# Usage (from the repository folder):
#   powershell -ExecutionPolicy Bypass -File install.ps1 [-Python C:\Path\to\python.exe]
# Creates .venv in this folder, installs the requirements into it, registers a scheduled
# task and starts it. Re-run after editing config.json or updating the code.
param(
  [string]$Python = "",            # base interpreter used to create the venv
  [string]$TaskName = "eiscp-autopower"
)
$ErrorActionPreference = "Stop"
$dir = $PSScriptRoot
$script = Join-Path $dir "eiscp_autopower.py"
$venv = Join-Path $dir ".venv"
if (-not (Test-Path (Join-Path $dir "config.json"))) {
  throw "config.json not found. Copy config.example.json to config.json and edit it first."
}

if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) {
  if (-not $Python) {
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) { $Python = (& py.exe -3 -c "import sys; print(sys.executable)").Trim() }
    else { $Python = (Get-Command python.exe -ErrorAction Stop).Source }
  }
  Write-Host "Creating venv with $Python"
  & $Python -m venv $venv
  if ($LASTEXITCODE) { throw "venv creation failed" }
}
$vpy = Join-Path $venv "Scripts\python.exe"
$vpyw = Join-Path $venv "Scripts\pythonw.exe"
& $vpy -m pip install --disable-pip-version-check -q -r (Join-Path $dir "requirements.txt")
if ($LASTEXITCODE) { throw "pip install failed" }
& $vpy $script status
if ($LASTEXITCODE) { throw "the receiver did not answer; check 'host' in config.json" }

# $env:USERDOMAIN is "WORKGROUP" in some sessions (e.g. over SSH); ask Windows instead.
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $vpyw -Argument "`"$script`" run" -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartInterval (New-TimeSpan -Minutes 1) -RestartCount 999 `
  -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal `
  -Settings $settings -Description "Switch the AV receiver together with this PC (eiscp-autopower)" -Force | Out-Null

Get-CimInstance Win32_Process |
  Where-Object { $_.Name -eq "pythonw.exe" -and $_.CommandLine -match "eiscp_autopower" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-ScheduledTask -TaskName $TaskName
Write-Host "Registered and started task '$TaskName'. Log: $(Join-Path $dir 'eiscp-autopower.log')"
