@echo off
rem ===== AutoResearch 一键启动（双击即用） =====
cd /d %~dp0

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found.
    echo Run once:  python -m venv .venv  then  .venv\Scripts\python -m pip install -e ".[dev]"
    pause
    exit /b 1
)

echo Initializing database (idempotent)...
.venv\Scripts\autoresearch init >nul 2>&1

echo Starting AutoResearch dashboard at http://localhost:8501 ...
echo (close this window to stop the app)
.venv\Scripts\python -m streamlit run src\autoresearch\ui\app.py --server.port 8501 --browser.gatherUsageStats false
pause
