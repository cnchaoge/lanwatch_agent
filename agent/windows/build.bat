@echo off
chcp 65001 >nul
echo ========================================
echo   Lanwatch Agent v1.3.0 构建脚本
echo ========================================
echo.

cd /d "%~dp0"

echo [1/4] 检查 Python...
python --version 2>nul || (echo ERROR: Python not found & pause & exit /b 1)

echo [2/4] 创建虚拟环境（如果不存在）...
if not exist "venv\Scripts\python.exe" (
    python -m venv venv
    echo 虚拟环境创建完成
)

echo [3/4] 安装依赖...
call venv\Scripts\activate.bat
pip install --upgrade pip -q
pip install pystray pillow pyinstaller httpx pysnmp pywin32 -q
pip install -r requirements.txt -q
echo 依赖安装完成

echo [4/4] 执行 PyInstaller...
pyinstaller setup\build_spec.py --noconfirm --clean

echo.
echo ========================================
echo   构建完成！
echo   输出目录: dist\LanwatchAgent.exe
echo ========================================
pause
