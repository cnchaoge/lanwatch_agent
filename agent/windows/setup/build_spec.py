"""
PyInstaller 打包配置：
运行：pip install pyinstaller && python build_spec.py

这会生成单一的可执行文件 LanwatchAgent.exe
"""
block_cipher = None

a = Analysis(
    ["../main.py"],
    pathex=[".."],
    binaries=[],
    datas=[],
    hiddenimports=[
        "pysnmp.hlapi", "pysnmp.hlapi.asyncio",
        "httpx", "dns.resolver", "dns.exception",
        "win32serviceutil", "win32service", "win32event", "servicemanager"
    ],
    win_private_assemblies=True,
    cipher=block_cipher
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="LanwatchAgent",
    debug=False,
    strip=False,
    upx=True,
    console=True,  # 保留控制台以便查看日志
    version="version_info.txt"  # 可选：Windows 版本信息
)
