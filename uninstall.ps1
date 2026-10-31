# Remove the logon task and stop the running agent. Delete the folder (including .venv) afterwards if you like.
param([string]$TaskName = "eiscp-autopower")
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -eq "pythonw.exe" -and $_.CommandLine -match "eiscp_autopower" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Write-Host "Removed task '$TaskName'."
