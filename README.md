# Web Research Tool

Version: 1.2

## Installation and start

Use the startup scripts from the project root.

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
