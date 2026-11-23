@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
set "OMP_NUM_THREADS=2"
set "OPENBLAS_NUM_THREADS=2"
".venv\Scripts\python.exe" -m uvicorn api.main:app --host 127.0.0.1 --port 8038
