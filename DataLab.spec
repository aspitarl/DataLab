# -*- mode: python ; coding: utf-8 -*-

# Initial command:
# pyinstaller -y --clean -n DataLab -i resources\DataLab.ico cdlapp\start.pyw

import os.path as osp
import guidata
guidata_path = osp.dirname(guidata.__file__)
guidata_images = osp.join(guidata_path, 'images')
guidata_locale = osp.join(guidata_path, 'locale', 'fr', 'LC_MESSAGES')
import plotpy
plotpy_path = osp.dirname(plotpy.__file__)
plotpy_images = osp.join(plotpy_path, 'images')
plotpy_locale = osp.join(plotpy_path, 'locale', 'fr', 'LC_MESSAGES')

from PyInstaller.utils.hooks import collect_submodules
all_hidden_imports = collect_submodules('cdlapp')

a = Analysis(
    ['cdlapp\\start.pyw'],
    pathex=[],
    binaries=[],
    datas=[
        (guidata_images, 'guidata\\images'),
        (guidata_locale, 'guidata\\locale\\fr\\LC_MESSAGES'),
        (plotpy_images, 'plotpy\\images'),
        (plotpy_locale, 'plotpy\\locale\\fr\\LC_MESSAGES'),
        ('cdlapp\\plugins', 'cdlapp\\plugins'),
        ('cdlapp\\data', 'cdlapp\\data'),
        ('cdlapp\\locale\\fr\\LC_MESSAGES\\cdlapp.mo', 'cdlapp\\locale\\fr\\LC_MESSAGES'),
        ],
    hiddenimports=all_hidden_imports,
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
    [],
    exclude_binaries=True,
    name='DataLab',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['resources\\DataLab.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='DataLab',
)
