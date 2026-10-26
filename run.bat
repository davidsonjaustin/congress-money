@echo off
cd /d "%~dp0"
echo Congress Money Tracker - open http://127.0.0.1:8000 (Ctrl+C to stop)
start "" http://127.0.0.1:8000
".venv\Scripts\python.exe" -m uvicorn server.api:app --port 8000
