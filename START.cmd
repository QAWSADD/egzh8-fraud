@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 exit /b 1
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8038/health',timeout=1)" >nul 2>nul
if errorlevel 1 start "EGZH-8 API" cmd /k API_START.cmd
".venv\Scripts\python.exe" -c "import time,urllib.request; url='http://127.0.0.1:8038/health'; exec('for _ in range(20):\n try:\n  urllib.request.urlopen(url,timeout=1).close(); break\n except OSError:\n  time.sleep(.4)')"
".venv\Scripts\python.exe" app\ui.py
