# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for JARVIS AI (Phase 19).

Builds a single-file Windows executable that bundles Python, every
dependency, and the .env.example template. The Flet desktop client is
cached in the user profile (~/.flet) on first run, so end users do not
need to install anything.

Build with:
    pyinstaller jarvis.spec
"""

from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = collect_all("flet")
flet_desktop_datas, flet_desktop_binaries, flet_desktop_hidden = collect_all(
    "flet_desktop"
)

# Ship the env template so API keys can be configured next to the exe.
datas += [(".env.example", ".")]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries + flet_desktop_binaries,
    datas=datas + flet_desktop_datas,
    hiddenimports=hiddenimports + flet_desktop_hidden,
    hookspath=[],
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
    name="JARVIS AI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # GUI app - no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)