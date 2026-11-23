@echo off
cd /d "%~dp0"
set "OMP_NUM_THREADS=2"
set "OPENBLAS_NUM_THREADS=2"
".venv\Scripts\python.exe" -m pytest -q %*
