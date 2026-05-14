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
        # PIL 插件（我们只用到 Image.new + ImageDraw，不需格式插件）
        "PIL.JpegImagePlugin", "PIL.JpegPresets",
        "PIL.PngImagePlugin", "PIL.GifImagePlugin",
        "PIL.BmpImagePlugin", "PIL.TiffImagePlugin",
        "PIL.WebPImagePlugin", "PIL.IcoImagePlugin",
        "PIL.IcnsImagePlugin", "PIL.TgaImagePlugin",
        "PIL.PcxImagePlugin", "PIL.PpmImagePlugin",
        "PIL.PsdImagePlugin", "PIL.XbmImagePlugin",
        "PIL.XpmImagePlugin", "PIL.DdsImagePlugin",
        "PIL.ImImagePlugin", "PIL.MspImagePlugin",
        "PIL.SgiImagePlugin", "PIL.FpxImagePlugin",
        "PIL.FtexImagePlugin", "PIL.GbrImagePlugin",
        "PIL.MicImagePlugin", "PIL.MpoImagePlugin",
        "PIL.PcdImagePlugin", "PIL.PixarImagePlugin",
        "PIL.WalImageFile",
        # PIL 功能模块（未使用）
        "PIL.ImageFilter", "PIL.ImageFont", "PIL.ImageEnhance",
        "PIL.ImageGrab", "PIL.ImageQt", "PIL.ImageCms",
        "PIL.ImageSequence", "PIL.ImageStat", "PIL.ImageColor",
        "PIL.ImageChops", "PIL.ImageOps", "PIL.ImageTransform",
        "PIL.ImagePalette", "PIL.ImagePath", "PIL.ImageMode",
        # 标准库（不需要）
        "tkinter.test", "unittest", "email", "http.server",
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