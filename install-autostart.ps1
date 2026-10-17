# Makes Constantinople Station start automatically when you log in to Windows and restart itself if it stops.
# Run once from the engine folder:   powershell -ExecutionPolicy Bypass -File .\install-autostart.ps1
$here = $PSScriptRoot
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) {
  $action  = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$here\start-station.ps1`"" -WorkingDirectory $here
  $trigger = New-ScheduledTaskTrigger -AtLogOn
  $settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 3650) -StartWhenAvailable
  Register-ScheduledTask -TaskName "Constantinople Station" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
  Start-ScheduledTask -TaskName "Constantinople Station"
  Write-Host "Installed as a scheduled task. Stop: Stop-ScheduledTask -TaskName 'Constantinople Station'  Remove: Unregister-ScheduledTask -TaskName 'Constantinople Station' -Confirm:`$false" -ForegroundColor Green
} else {
  $startup = [Environment]::GetFolderPath('Startup')
  $vbs = "$startup\Constantinople Station.vbs"
  Set-Content $vbs "CreateObject(""WScript.Shell"").Run ""powershell -WindowStyle Hidden -ExecutionPolicy Bypass -File """"$here\start-station.ps1"""""", 0, False"
  wscript $vbs
  Write-Host "Installed in your Startup folder (no admin needed). The station is starting now and will start at every login." -ForegroundColor Green
  Write-Host "Stop it:   powershell -ExecutionPolicy Bypass -File .\stop-station.ps1" 
  Write-Host "Remove:    del `"$vbs`""
}
Write-Host "Dashboard: http://127.0.0.1:8787"
