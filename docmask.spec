# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：生成单文件、带控制台的 docmask.exe。"""

a = Analysis(
    ["packaging/windows_entry.py"],
    pathex=[],
    binaries=[],
    datas=[("docmask/web/static", "docmask/web/static")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "scipy", "pytest"],
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
    name="docmask",
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
