# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from os.path import abspath, join, dirname, pardir
from PyInstaller.building.build_main import Analysis, PYZ, EXE, COLLECT, BUNDLE, Splash
from PyInstaller.compat import is_linux
try:
    from exhale.appversion import exhale_version
except ModuleNotFoundError as e:
    print("WARNING: Failed to get exhale version.\n"
          "Install exhale with 'pip install -e .'")
    exhale_version = "EXHALE"

#sys.modules['FixTk'] = None

import napari
BUNDLE_ROOT = abspath(join(dirname(napari.__file__), pardir, 'bundle'))

a = Analysis(
    ['../run_exhale.py'],
    pathex=[],
    binaries=[],
    hiddenimports=['pkg_resources.py2_warn', 'importlib'],
    hooksconfig={"matplotlib": {"backends": "Agg"}},
    runtime_hooks=[],
    datas=[],
    hookspath=[join(BUNDLE_ROOT, 'hooks'),
        join(dirname(sys.argv[0]), 'hooks')],
    excludes=[
#        'FixTk', 'tcl', 'tk', '_tkinter', 'tkinter', 'Tkinter',
        'torch', 'tensorflow', 'nvidia', 'numba', 'matplotlib.TkAgg',
        'hdf5plugin', 'pyarrow', 'babel'
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

do_splash = True
onefile = True#not is_linux
strip = False

strip = is_linux and strip

if do_splash:
    splash = Splash('exhale_splash.jpg',
                    binaries=a.binaries,
                    datas=a.datas,
                    text_pos=(10, 40),
                    text_size=11,
                    text_color='#a070ff',
                    text_default=f"Loading EXHALE {exhale_version}")

    toexec = ([a.scripts, a.binaries, a.datas, splash, splash.binaries]
              if onefile else [splash, a.scripts])
    tocoll = [a.binaries, a.datas, splash.binaries] if not onefile else []
else:
    toexec = [a.binaries, a.datas] if onefile else []
    tocoll = [a.binaries, a.datas] if not onefile else []

exe = EXE(
    pyz,
    *toexec,
    [],
    exclude_binaries=not onefile,
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

if not onefile:
    coll = COLLECT(
        exe,
        *tocoll,
        strip=strip,
        upx=True,
        upx_exclude=[],
        name='exhale',
    )
