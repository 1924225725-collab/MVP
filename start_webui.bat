@echo off
rem ============================================
rem  AI Live Clipper - Web UI Launcher
rem  Double-click this file to start the app.
rem ============================================
cd /d "%~dp0"

if not exist ".venv\Scripts\streamlit.exe" (
    echo [ERROR] streamlit not found in .venv
    echo Please run: .venv\Scripts\python -m pip install streamlit
    pause
    exit /b 1
)

echo Starting AI Live Clipper Web UI...
echo Browser will open at http://localhost:8501
echo To stop the app, just close this window.
echo.

".venv\Scripts\streamlit.exe" run ui.py

pause
