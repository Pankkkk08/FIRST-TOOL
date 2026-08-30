# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for Squeeze.

Build from the repo root with:  pyinstaller packaging/squeeze.spec
(PyInstaller doesn't cross-compile — run this on the OS you want the
executable for.) Output lands in dist/Squeeze (dist/Squeeze.exe on
Windows, dist/Squeeze.app on macOS).

This bundles the Python/pywebview/Pillow side plus the webui/static/
HTML+CSS+JS assets — ffmpeg itself is NOT bundled (it's a large,
license-bearing external binary), so the Video tab still needs a system
ffmpeg install. See packaging/README.md.

The UI is rendered by the OS's own webview (WebView2 on Windows, WebKit
on macOS/Linux) rather than bundled — pywebview talks to whatever's
already on the system, so there's no browser engine to ship here either.
Linux end users need the webkit2gtk system package installed (see
packaging/README.md); Windows/macOS ship a webview by default.
"""

import os
import sys

repo_root = os.path.abspath(os.path.join(SPECPATH, os.pardir))
static_dir = os.path.join(repo_root, "squeeze", "webui", "static")

a = Analysis(
    [os.path.join(repo_root, "run_squeeze.py")],
    pathex=[repo_root],
    binaries=[],
    datas=[(static_dir, os.path.join("squeeze", "webui", "static"))],
    hiddenimports=["squeeze", "squeeze.core", "squeeze.webui"],
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
    name="Squeeze",
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
)

if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="Squeeze.app",
        icon=None,
        bundle_identifier="local.tools.squeeze",
    )
