# Starts the whole Zoikorum dev stack: database, API, worker and frontend.
# Usage (PowerShell, from the repo root):   .\start-dev.ps1
# Each server opens in its own window; close a window (or Ctrl+C) to stop it.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$venv = Join-Path $root ".venv\Scripts"

Write-Host "1/4 Starting database (Docker)..." -ForegroundColor Cyan
docker compose -f (Join-Path $root "docker-compose.yml") up -d
if ($LASTEXITCODE -ne 0) { Write-Host "Docker is not running. Open Docker Desktop and run this script again." -ForegroundColor Red; exit 1 }

Write-Host "    Applying database migrations..." -ForegroundColor Cyan
Push-Location $backend
try {
  & "$venv\alembic.exe" upgrade head
  if ($LASTEXITCODE -ne 0) { throw "Database migration failed. API and worker were not started." }
  & "$venv\alembic.exe" check
  if ($LASTEXITCODE -ne 0) { throw "Database schema does not match the code. API and worker were not started." }
} finally {
  Pop-Location
}

Write-Host "2/4 Starting API on http://localhost:8000 ..." -ForegroundColor Cyan
Start-Process powershell -WorkingDirectory $backend -ArgumentList "-NoExit", "-Command",
  "`$host.UI.RawUI.WindowTitle='Zoikorum API'; & '$venv\uvicorn.exe' zoikorum.main:app --reload --port 8000"

Write-Host "3/4 Starting worker..." -ForegroundColor Cyan
Start-Process powershell -WorkingDirectory $backend -ArgumentList "-NoExit", "-Command",
  "`$host.UI.RawUI.WindowTitle='Zoikorum Worker'; & '$venv\python.exe' -m zoikorum.worker"

Write-Host "4/4 Starting frontend on http://localhost:5173 ..." -ForegroundColor Cyan
Start-Process powershell -WorkingDirectory $frontend -ArgumentList "-NoExit", "-Command",
  "`$host.UI.RawUI.WindowTitle='Zoikorum Frontend'; npm run dev"

# Wait for the API before opening the browser.
for ($i = 0; $i -lt 30; $i++) {
  try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health -TimeoutSec 2 | Out-Null; break } catch { Start-Sleep 1 }
}
Start-Sleep 2
Start-Process "http://localhost:5173/login"
Write-Host "Zoikorum is running. Keep the three server windows open." -ForegroundColor Green
