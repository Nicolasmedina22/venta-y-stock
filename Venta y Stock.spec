# -*- mode: python ; coding: utf-8 -*-

# -*- mode: python ; coding: utf-8 -*-
#
# Nota sobre FALSOS POSITIVOS DE ANTIVIRUS:
# Un .exe hecho con PyInstaller se marca a veces como sospechoso
# ("Trojan", "Wacatac", "Gen") aunque el programa sea legítimo.
# Las causas principales y cómo las evitamos aquí:
#   1) UPX  -> el empaquetado comprimido es la causa #1 de falsos
#             positivos. Se desactiva con upx=False.
#   2) Un .exe "onefile" se auto-extrae en %TEMP% en cada arranque
#             (comportamiento típico de malware). Se evita generando
#             un único directorio con COLLECT ("onedir") y un
#             EXE simple, sin auto-extracción.
#   3) Versión: un ejecutable sin metadatos de versión ni autor
#             es más sospechoso. Se agrega version=version_info.txt.

import os
import sys

# Raíz del proyecto (donde vive este .spec).
BASE_DIR = os.path.abspath(os.getcwd())

a = Analysis(
    ["app.py"],
    pathex=[BASE_DIR],
    binaries=[],
    datas=[("templates", "templates"), ("static", "static")],
    hiddenimports=["openpyxl"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["customtkinter", "tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Venta y Stock",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version="version_info.txt",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Venta y Stock",
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Venta y Stock",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)