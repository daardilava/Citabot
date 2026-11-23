@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Preparando el entorno por primera vez...
  where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
  .venv\Scripts\python.exe -m pip install --quiet -e .
)
.venv\Scripts\python.exe run.py
pause
