# Stops the station (the restart loop and the engine). Start again with start-station.ps1 or the Startup shortcut.
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*start-station*' -or $_.CommandLine -like '*constantinople serve*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Write-Host "Constantinople Station stopped." -ForegroundColor Yellow
