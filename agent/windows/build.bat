@echo off
chcp 65001 >nul

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

echo ========================================
echo    Lanwatch Agent v1.3.0 Build Script
echo ========================================
echo.

echo [1/4] Checking Python...
python --version 2>nul
if errorlevel 1 (
    echo ERROR: Python not found
    pause
    exit /b 1
)

echo [2/4] Creating virtual environment...
if not exist "venv\Scripts\python.exe" (
    python -m venv venv
)

echo [3/4] Installing dependencies...
call venv\Scripts\activate.bat
pip install --upgrade pip -q
pip install pystray pillow pyinstaller httpx pywin32 -q
pip install -r requirements.txt -q

echo [4/4] Running PyInstaller...
pyinstaller setup\build_spec.py --noconfirm --clean

echo.
echo ========================================
echo    Build complete!
echo    Output: dist\LanwatchAgent.exe
echo ========================================
pause
