# Remove the logon task and stop the running agent. Delete the folder (including .venv) afterwards if you like.
param([string]$TaskName = "eiscp-autopower")
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
# Stop only the agent started from this folder (another copy may be installed elsewhere).
$mine = Join-Path $PSScriptRoot "eiscp_autopower.py"
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -eq "pythonw.exe" -and $_.CommandLine -and $_.CommandLine.Contains($mine) } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Write-Host "Removed task '$TaskName'."
