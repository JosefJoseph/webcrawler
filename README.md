# Web Research Tool

Version: 2.1

## Installation and start

Use the startup scripts from the project root.

## Testing

python -m pytest tests/

## macOS / Linux

If needed, make the shell script executable once:

```bash
chmod +x run_app.sh
```

Start the app with:

```bash
./run_app.sh
```

## Windows

### PowerShell
```powershell
./run_app.bat
```

### CMD
```cmd
run_app.bat
```

## Manual start fallback

If the startup scripts do not work in your environment, you can start the app manually.

### macOS / Linux

```bash
pip install -r requirements.txt
python -m playwright install chromium
PYTHONPATH=. streamlit run app/ui/streamlit_app.py
```

### Windows PowerShell

```powershell
pip install -r requirements.txt
python -m playwright install chromium
$env:PYTHONPATH="."
streamlit run app/ui/streamlit_app.py
```

### Windows CMD

```cmd
pip install -r requirements.txt
python -m playwright install chromium
set PYTHONPATH=.
streamlit run app/ui/streamlit_app.py
```

---

## Troubleshooting: PyTorch Compatibility on macOS (Apple Silicon)

If you are using a Mac with Apple Silicon (M1/M2/M3/M4) and encounter issues with **Semantic Search** (which requires PyTorch and sentence-transformers), follow these steps:

### 1. Use a compatible Python version

PyTorch requires a native **arm64** Python build. Python 3.13 is recommended.

> **Do not** use Homebrew x86_64 Python or Rosetta-translated Python — PyTorch wheels may not be available for those builds.

### 2. Install `uv` (if not already installed)

```bash
pip install uv
```

### 3. Create a virtual environment with the correct architecture

```bash
uv venv .venv --python cpython-3.13-macos-aarch64-none
source .venv/bin/activate
uv pip install -r requirements.txt
```

This ensures your environment uses a native arm64 Python, which is required for PyTorch on Apple Silicon.

### 4. Verify your Python architecture

```bash
python -c "import platform; print(platform.machine())"
```

This should print:

```
arm64
```

If it prints `x86_64`, your Python is running under Rosetta and PyTorch may not work correctly.

### 5. Further help

For more details, see the official [PyTorch installation guide](https://pytorch.org/get-started/locally/).
