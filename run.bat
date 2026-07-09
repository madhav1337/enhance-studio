@echo off
REM Enhance Studio launcher (Windows).
REM Uses a local .venv if present, otherwise falls back to the system Python.
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" app.py
) else (
    python app.py
)
