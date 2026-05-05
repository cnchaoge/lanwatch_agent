# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置 v1.3.0 — 单文件 exe，GUI 托盘模式
运行：pyinstaller LanwatchAgent.spec --noconfirm --clean
"""
import os

WORK_DIR = os.path.dirname(os.path.abspath(SPECPATH))
PARENT_DIR = os.path.dirname(WORK_DIR)  # windows/

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
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="LanwatchAgent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
    version=os.path.join(PARENT_DIR, "version_info.txt"),
)
