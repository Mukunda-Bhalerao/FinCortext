# Starts the backend (port 8000) and frontend (port 5173) together. Ctrl+C stops both.
$root = $PSScriptRoot
$py = Join-Path $root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Error "Backend environment missing. See README.md > Setup."; exit 1 }
if (-not (Test-Path (Join-Path $root "frontend\node_modules"))) { Write-Error "Run 'npm install' in frontend first."; exit 1 }

$backend = Start-Process -FilePath $py -ArgumentList "-m", "uvicorn", "app.main:app", "--port", "8000" `
    -WorkingDirectory (Join-Path $root "backend") -NoNewWindow -PassThru
try {
    npm --prefix (Join-Path $root "frontend") run dev
}
finally {
    if (-not $backend.HasExited) { Stop-Process -Id $backend.Id -Force }
}
