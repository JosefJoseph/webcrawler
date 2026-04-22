#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="$ROOT_DIR/.venv"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Error: $PYTHON_BIN is not installed or not in PATH."
  exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtual environment..."
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

VENV_PYTHON="$VENV_DIR/bin/python"

if [ ! -x "$VENV_PYTHON" ]; then
  echo "Error: virtual environment Python was not created correctly."
  exit 1
fi

if ! "$VENV_PYTHON" -c "import importlib.util, sys; required=('requests', 'bs4', 'lxml', 'streamlit', 'playwright', 'fpdf', 'tabulate'); sys.exit(0 if all(importlib.util.find_spec(name) for name in required) else 1)" >/dev/null 2>&1; then
  echo "Upgrading pip..."
  "$VENV_PYTHON" -m pip install --upgrade pip

  echo "Installing Python requirements..."
  "$VENV_PYTHON" -m pip install -r requirements.txt
else
  echo "Python requirements already available. Skipping installation."
fi

if ! "$VENV_PYTHON" -c "import os, sys; from playwright.sync_api import sync_playwright; p = sync_playwright().start(); path = p.chromium.executable_path; p.stop(); sys.exit(0 if os.path.exists(path) else 1)" >/dev/null 2>&1; then
  echo "Installing Playwright Chromium browser..."
  "$VENV_PYTHON" -m playwright install chromium
else
  echo "Playwright Chromium browser already available. Skipping installation."
fi

echo "Starting Streamlit app..."
export PYTHONPATH="$ROOT_DIR"
exec "$VENV_PYTHON" -m streamlit run app/ui/streamlit_app.py
