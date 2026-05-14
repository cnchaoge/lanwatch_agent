@echo off
chcp 65001 >nul

:: 自动获取脚本所在目录（支持任意盘符）
set "WORK_DIR=%~dp0"
set "WORK_DIR=%WORK_DIR:~0,-1%"
cd /d "%WORK_DIR%"

echo ========================================
echo    Lanwatch Agent v1.3.0 Build Script
echo ========================================
echo [WORKDIR] %WORK_DIR%
echo.

echo [1/4] Checking Python 3.12...
py -3.12 --version 2>nul
if errorlevel 1 (
    echo ERROR: Python 3.12 not found
    pause
    exit /b 1
)

echo [2/4] Creating virtual environment...
if not exist "%WORK_DIR%\venv312\Scripts\python.exe" (
    py -3.12 -m venv "%WORK_DIR%\venv312"
)

echo [3/4] Installing dependencies...
"%WORK_DIR%\venv312\Scripts\pip.exe" install --upgrade pip -q
"%WORK_DIR%\venv312\Scripts\pip.exe" install pystray pillow pyinstaller httpx pywin32 -q
"%WORK_DIR%\venv312\Scripts\pip.exe" install -r "%WORK_DIR%\requirements.txt" -q

echo [4/4] Running PyInstaller...
"%WORK_DIR%\venv312\Scripts\python.exe" -m PyInstaller "%WORK_DIR%\setup\build_spec.py" --noconfirm --clean

echo.
echo ========================================
echo    Build complete!
echo ========================================
pause
