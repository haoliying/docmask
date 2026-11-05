# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：桌面版 docmask.exe + 命令行版 docmask-cli.exe。"""

from PyInstaller.utils.hooks import collect_data_files

base_datas = [
    ("docmask/web/static", "docmask/web/static"),
    ("assets/docmask.ico", "assets"),
]

# pywebview 自带 WebView2 加载器与注入脚本，显式收集避免不同 hook 版本遗漏。
try:
    webview_datas = collect_data_files("webview")
except Exception:
    webview_datas = []

excludes = ["tkinter", "matplotlib", "numpy", "pandas", "scipy", "pytest"]

gui = Analysis(
    ["packaging/windows_entry.py"],
    pathex=[],
    binaries=[],
    datas=base_datas + webview_datas,
    hiddenimports=[
        "webview",
        "webview.platforms.edgechromium",
        "clr",
        "clr_loader",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
gui_pyz = PYZ(gui.pure)
gui_exe = EXE(
    gui_pyz,
    gui.scripts,
    gui.binaries,
    gui.datas,
    [],
    name="docmask",
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
    icon="assets/docmask.ico",
)

cli = Analysis(
    ["packaging/windows_cli_entry.py"],
    pathex=[],
    binaries=[],
    datas=base_datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
cli_pyz = PYZ(cli.pure)
cli_exe = EXE(
    cli_pyz,
    cli.scripts,
    cli.binaries,
    cli.datas,
    [],
    name="docmask-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/docmask.ico",
)
