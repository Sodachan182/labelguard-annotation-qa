@echo off
rem LabelGuard one-click launcher for Windows.
rem   Double-click to start.  "START_LABELGUARD.bat --check" sets up and verifies without launching.
setlocal EnableExtensions
cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if exist "%VENV_PY%" goto :deps

echo [LabelGuard] Looking for Python 3.12 ...
set "BASE_PY="
py -3.12 -c "import sys" >nul 2>nul && set "BASE_PY=py -3.12"
if not defined BASE_PY (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul && set "BASE_PY=python"
)
if not defined BASE_PY (
  echo [LabelGuard] Python 3.12 or newer was not found. Install it from https://www.python.org/downloads/
  goto :fail
)
echo [LabelGuard] Creating virtual environment in .venv ...
%BASE_PY% -m venv "%~dp0.venv" || goto :fail

:deps
"%VENV_PY%" -c "import labelguard, streamlit" >nul 2>nul
if errorlevel 1 (
  echo [LabelGuard] Installing dependencies - first run only ...
  "%VENV_PY%" -m pip install --disable-pip-version-check --quiet --upgrade pip || goto :fail
  "%VENV_PY%" -m pip install --disable-pip-version-check --quiet -e "%~dp0." || goto :fail
)
"%VENV_PY%" -c "import labelguard; print('[LabelGuard] version', labelguard.__version__)" || goto :fail

if /i "%~1"=="--check" (
  echo [LabelGuard] Environment OK. Not launching because --check was given.
  exit /b 0
)

echo [LabelGuard] Starting on http://localhost:8501 - the browser opens when the app is ready.
echo [LabelGuard] Close this window or press Ctrl+C to stop.
"%VENV_PY%" -m streamlit run "%~dp0app.py" --server.port 8501 --server.headless false
exit /b %errorlevel%

:fail
echo [LabelGuard] Setup failed. See the messages above.
pause
exit /b 1
