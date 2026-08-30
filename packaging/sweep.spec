# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for Sweep.

Build from the repo root with:  pyinstaller packaging/sweep.spec
(PyInstaller doesn't cross-compile — run this on the OS you want the
executable for.) Output lands in dist/Sweep (dist/Sweep.exe on Windows,
dist/Sweep.app on macOS).
"""

import os
import sys

repo_root = os.path.abspath(os.path.join(SPECPATH, os.pardir))

a = Analysis(
    [os.path.join(repo_root, "run_sweep.py")],
    pathex=[repo_root],
    binaries=[],
    datas=[],
    hiddenimports=["sweep", "sweep.core", "sweep.gui"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Sweep",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # windowed app, no terminal popping up alongside it
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="Sweep.app",
        icon=None,
        bundle_identifier="local.tools.sweep",
    )
