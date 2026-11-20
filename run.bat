@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Chua cai dat moi truong Python trong D:\Chess\.venv.
    echo Xem README.md de cai dat.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "stockfish_review.py"
