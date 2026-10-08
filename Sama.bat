@echo off
REM One-click launcher: installs everything on first run, then starts Sama.
cd /d "%~dp0"
where python >nul 2>nul || (echo Install Python 3.10+ from python.org first & pause & exit /b 1)
if not exist .venv (
  python -m venv .venv
  call .venv\Scripts\activate.bat
  pip install -r requirements.txt
) else (
  call .venv\Scripts\activate.bat
)
where ollama >nul 2>nul || (
  echo Ollama not found. Installing via winget...
  winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
)
ollama list 2>nul | findstr /i "qwen2.5" >nul || ollama pull qwen2.5:7b-instruct
ollama list 2>nul | findstr /i "qwen2.5vl" >nul || ollama pull qwen2.5vl:7b
python -m sama
