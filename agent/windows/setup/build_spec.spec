"""
PyInstaller 打包配置（v1.3.1 — 精简依赖）
运行：pyinstaller build_spec.spec --noconfirm --clean
"""
import os
from PyInstaller.building.build_main import Analysis, PYZ, EXE

WORK_DIR = os.path.join(os.getcwd(), "setup")
PARENT_DIR = os.getcwd()

a = Analysis(
    [os.path.join(PARENT_DIR, "lanwatch_agent.py")],
    pathex=[PARENT_DIR],
    binaries=[],
    datas=[
        (os.path.join(PARENT_DIR, "core"), "core"),
        (os.path.join(PARENT_DIR, "probes"), "probes"),
        (os.path.join(PARENT_DIR, "version_info.txt"), "."),
    ],
    hiddenimports=[
        "pystray", "PIL.Image", "PIL.ImageDraw",
        "urllib.request", "urllib.error", "urllib.parse",
        "win32serviceutil", "win32service", "win32event",
        "win32api", "win32con", "win32process", "win32gui",
        "win32timezone", "pythoncom", "pywintypes",
    ],
    excludes=[
        # 标准库（不需要）
        "tkinter.test", "unittest", "http.server",
        "pydoc", "doctest", "difflib",
    ],
)

pyz = PYZ(a.pure)

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