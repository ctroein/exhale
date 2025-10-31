# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from os.path import abspath, join, dirname, pardir
from PyInstaller.building.build_main import Analysis, PYZ, EXE, COLLECT, BUNDLE
from PyInstaller.compat import is_linux

#sys.modules['FixTk'] = None

import napari

BUNDLE_ROOT = abspath(join(dirname(napari.__file__), pardir, 'bundle'))

a = Analysis(
    ['../run_exhale.py'],
    pathex=[],
    binaries=[],
    hiddenimports=['pkg_resources.py2_warn', 'importlib'],
    hooksconfig={},
    runtime_hooks=[],
    datas=[],
    hookspath=[join(BUNDLE_ROOT, 'hooks'),
        join(dirname(sys.argv[0]), 'hooks')],
    excludes=[
#        'FixTk', 'tcl', 'tk', '_tkinter', 'tkinter', 'Tkinter',
        'torch', 'tensorflow', 'nvidia'
    ],
    noarchive=False,
    optimize=0,
)
#pyz = PYZ(a.pure)

splash = Splash('exhale_splash.jpg',
                binaries=a.binaries,
                datas=a.datas,
                text_pos=(10, 50),
                text_size=10,
                text_color='white')

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

onefile = not is_linux

toexec = [splash.binaries] if not is_linux else []
tocoll = [splash.binaries] if is_linux else []

strip = True
strip = is_linux and strip

exe = EXE(
    pyz,
    a.scripts,
    splash
    *toexec,
    [],
    exclude_binaries=True,
    name='exhale',
    debug=False,
    bootloader_ignore_signals=False,
    strip=strip,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=join(pardir, 'exhale', 'resources', 'lungs.ico'),
)


coll = COLLECT(
    exe,
    *tocoll,
    strip=strip,
    upx=True,
    upx_exclude=[],
    name='exhale',
)
