Set-Location "$PSScriptRoot\..\orchestrator"
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
& ".venv\Scripts\Activate.ps1"
pip install -q -r requirements.txt
if (-not (Test-Path ".env")) {
    Write-Error "orchestrator\.env not found - copy .env.example to .env and fill it in (see docs\SETUP.md)."
    exit 1
}
uvicorn app.main:app --host 0.0.0.0 --port 8080
