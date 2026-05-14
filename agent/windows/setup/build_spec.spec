"""
PyInstaller 打包配置（v1.3.0 — GUI 托盘模式，目录模式 exe）
运行：pyinstaller build_spec.spec --noconfirm --clean
"""
import os
from PyInstaller.building.build_main import Analysis, PYZ, EXE

WORK_DIR = os.path.join(os.getcwd(), "setup")  # setup/
PARENT_DIR = os.getcwd()                        # windows/

block_cipher = None

a = Analysis(
    [os.path.join(PARENT_DIR, "lanwatch_agent.py")],
    pathex=[PARENT_DIR],
    binaries=[],
    datas=[
        (os.path.join(PARENT_DIR, "network_monitor.py"), "."),
        (os.path.join(PARENT_DIR, "core"), "core"),
        (os.path.join(PARENT_DIR, "probes"), "probes"),
        (os.path.join(PARENT_DIR, "version_info.txt"), "."),
    ],
    hiddenimports=[
        "pystray", "pillow", "PIL", "PIL.Image", "PIL.ImageDraw",
        "httpx", "httpx._client", "httpx._models",
        "win32serviceutil", "win32service", "win32event",
        "win32api", "win32con", "win32process", "win32gui",
        "win32timezone", "pythoncom", "pywintypes",
    ],
    cipher=block_cipher
)

pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="LanwatchAgent",
    debug=False,
    strip=False,
    upx=True,
    console=False,
    version=os.path.join(PARENT_DIR, "version_info.txt")
)