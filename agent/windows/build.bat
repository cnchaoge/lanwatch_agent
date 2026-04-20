@echo off
:: lanwatch_agent v0.5 打包脚本
chcp 65001 >nul
echo 开始打包 lanwatch_agent v0.5...

cd /d %~dp0

:: 安装依赖
echo 安装依赖...
pip install -r requirements.txt -q

:: 清理旧构建
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

:: PyInstaller 打包
echo 正在打包...
python -m PyInstaller lanwatch_agent.spec --clean

if exist dist\lanwatch_agent.exe (
    echo.
    echo ========================================
    echo  打包成功！输出: dist\lanwatch_agent.exe
    echo ========================================
) else (
    echo 打包失败，请检查错误信息
)

pause
