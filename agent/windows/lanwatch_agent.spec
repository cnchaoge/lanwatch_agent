# -*- mode: python ; coding: utf-8 -*-
import sys

block_cipher = None

a = Analysis(
    ['lanwatch_agent.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        # GUI
        'tkinter', 'tkinter.ttk', 'tkinter.messagebox',
        'pystray', 'PIL', 'PIL._imaging', 'PIL.Image', 'PIL.ImageDraw',
        'PIL.ImageFont',
        # 网络
        'urllib.request', 'urllib.error', 'urllib.parse',
        # 标准库
        'json', 'socket', 'logging', 'logging.handlers',
        'threading', 'queue', 'concurrent.futures', 'concurrent.futures.as_completed',
        'ctypes', 're', 'subprocess', 'uuid', 'time', 'os', 'sys',
        'msvcrt',
        # Windows 专用
        'winreg',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='lanwatch_agent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
    version=None,
)
