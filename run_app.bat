@echo off
setlocal

cd /d "%~dp0"

set "VENV_DIR=%CD%\.venv"

where py >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON_CMD=py -3"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Error: Python is not installed or not in PATH.
        exit /b 1
    )
    set "PYTHON_CMD=python"
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo Creating virtual environment...
    call %PYTHON_CMD% -m venv "%VENV_DIR%"
    if errorlevel 1 exit /b 1
)

set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"

call "%VENV_PYTHON%" -c "import importlib.util, sys; required=('requests', 'bs4', 'lxml', 'streamlit', 'playwright', 'fpdf', 'tabulate'); sys.exit(0 if all(importlib.util.find_spec(name) for name in required) else 1)" >nul 2>nul
if errorlevel 1 (
    echo Upgrading pip...
    call "%VENV_PYTHON%" -m pip install --upgrade pip
    if errorlevel 1 exit /b 1

    echo Installing Python requirements...
    call "%VENV_PYTHON%" -m pip install -r requirements.txt
    if errorlevel 1 exit /b 1
) else (
    echo Python requirements already available. Skipping installation.
)

call "%VENV_PYTHON%" -c "import os, sys; from playwright.sync_api import sync_playwright; p = sync_playwright().start(); path = p.chromium.executable_path; p.stop(); sys.exit(0 if os.path.exists(path) else 1)" >nul 2>nul
if errorlevel 1 (
    echo Installing Playwright Chromium browser...
    call "%VENV_PYTHON%" -m playwright install chromium
    if errorlevel 1 exit /b 1
) else (
    echo Playwright Chromium browser already available. Skipping installation.
)

echo Starting Streamlit app...
set "PYTHONPATH=%CD%"
call "%VENV_PYTHON%" -m streamlit run app/ui/streamlit_app.py