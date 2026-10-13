# Runs the Zoikorum test suites.
# Usage (PowerShell, from anywhere):
#   & "<repo>\run-tests.ps1"                  # everything: backend unit + integration + regression, frontend unit, build
#   & "<repo>\run-tests.ps1" -Kind unit       # fast checks only (no database needed)
#   & "<repo>\run-tests.ps1" -Kind regression # end-to-end business flows (Steps 1-9)
# Backend integration and regression tests need the Docker database (docker compose up -d).

param([ValidateSet("all", "unit", "integration", "regression")] [string] $Kind = "all")

$root = $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
$failed = @()

function Step($title, [scriptblock] $run) {
  Write-Host "`n=== $title ===" -ForegroundColor Cyan
  & $run
  if ($LASTEXITCODE -ne 0) { $script:failed += $title; Write-Host "FAILED: $title" -ForegroundColor Red }
  else { Write-Host "OK: $title" -ForegroundColor Green }
}

Push-Location (Join-Path $root "backend")
if ($Kind -eq "all") {
  Step "Backend: all tests (unit + integration + regression)" { & $py -m pytest }
} else {
  Step "Backend: $Kind tests" { & $py -m pytest -m $Kind }
}
Pop-Location

if ($Kind -in @("all", "unit")) {
  Push-Location (Join-Path $root "frontend")
  Step "Frontend: unit tests" { npm test --silent }
  if ($Kind -eq "all") {
    Step "Frontend: lint" { npm run lint --silent }
    Step "Frontend: type-check and build" { npm run build --silent }
  }
  Pop-Location
}

if ($failed.Count -gt 0) {
  Write-Host "`nFailed: $($failed -join ', ')" -ForegroundColor Red
  exit 1
}
Write-Host "`nAll checks passed." -ForegroundColor Green
