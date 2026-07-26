$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Resolve-Path "$PSScriptRoot\..")
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8787 --app-dir web_app
