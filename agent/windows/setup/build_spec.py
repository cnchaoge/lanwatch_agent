"""
PyInstaller 打包配置（GUI 版本）
运行：pip install pyinstaller && python build_spec.py
生成单一可执行文件 LanwatchAgent.exe
"""
from PyInstaller.building.build_main import Analysis, PYZ
from PyInstaller.building.datastruct import Tree
from PyInstaller.building.make_main import EXE

block_cipher = None

a = Analysis(
    ["../lanwatch_agent.py"],
    pathex=[".."],
    binaries=[],
    datas=[],
    hiddenimports=[
        "pysnmp.hlapi", "pysnmp.hlapi.asyncio",
        "httpx", "dns.resolver", "dns.exception",
        "tkinter",
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
    console=False,
    version="version_info.txt"
)
