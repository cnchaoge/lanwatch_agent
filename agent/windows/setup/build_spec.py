"""
PyInstaller 打包配置（v1.3.0 — GUI 托盘模式，单文件 exe）
运行：pyinstaller build_spec.py --noconfirm --clean
"""
import os
from PyInstaller.building.build_main import Analysis, PYZ
from PyInstaller.building.make_main import EXE

block_cipher = None

a = Analysis(
    ["lanwatch_agent.py"],
    pathex=[os.path.abspath(".")],
    binaries=[],
    datas=[
        ("network_monitor.py", "."),
        ("core", "core"),
        ("probes", "probes"),
    ],
    hiddenimports=[
        "pystray", "pillow", "PIL", "PIL.Image", "PIL.ImageDraw",
        "httpx", "httpx._client", "httpx._models",
        "win32serviceutil", "win32service", "win32event",
        "win32api", "win32con", "win32process", "win32gui",
        "win32timezone", "pythoncom", "pywintypes",
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
    console=True,
    onefile=True,
    version="version_info.txt"
)
