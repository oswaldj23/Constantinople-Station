# Keeps the ship running: restarts the engine if it ever crashes. Run from the engine folder:
#   powershell -ExecutionPolicy Bypass -File .\start-station.ps1
Set-Location $PSScriptRoot
while ($true) {
  Write-Host "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  launching station..." -ForegroundColor Green
  python -m constantinople serve
  Write-Host "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  engine stopped (exit $LASTEXITCODE) - restarting in 10s. Ctrl+C twice to quit." -ForegroundColor Yellow
  Start-Sleep -Seconds 10
}
