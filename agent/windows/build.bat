@echo off
chcp 65001 >nul

set WORK_DIR=C:\Users\EWAY\lanwatch_agent\agent\windows
cd /d "%WORK_DIR%"

echo ========================================
echo    Lanwatch Agent v1.3.0 Build Script
echo ========================================
echo [WORKDIR] %cd%
echo.

echo [1/4] Checking Python...
python --version 2>nul
if errorlevel 1 (
    echo ERROR: Python not found
    pause
    exit /b 1
)

echo [2/4] Creating virtual environment...
if not exist "%WORK_DIR%\venv\Scripts\python.exe" (
    python -m venv "%WORK_DIR%\venv"
)

echo [3/4] Installing dependencies...
call "%WORK_DIR%\venv\Scripts\activate.bat"
pip install --upgrade pip -q
pip install pystray pillow pyinstaller httpx pywin32 -q
pip install -r "%WORK_DIR%\requirements.txt" -q

echo [4/4] Running PyInstaller...
pyinstaller "%WORK_DIR%\setup\build_spec.py" --noconfirm --clean

echo.
echo ========================================
echo    Build complete!
echo    Output: %WORK_DIR%\dist\LanwatchAgent.exe
echo ========================================
pause
