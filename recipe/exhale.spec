# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from os.path import abspath, join, dirname, pardir
from PyInstaller.building.build_main import Analysis, PYZ, EXE, COLLECT, BUNDLE, Splash
from PyInstaller.compat import is_linux
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

exhale_version = ""
try:
    from exhale.appversion import exhale_version
except ModuleNotFoundError:
    sys.path.insert(0, join(dirname(sys.argv[0]), pardir))
    try:
        from exhale.appversion import exhale_version
    except:
        print("WARNING: Failed to get exhale version.")
    del sys.path[0]
print("Building EXHALE", exhale_version)

icon_file = join(pardir, 'exhale', 'resources',
                 'lungs.icns' if sys.platform == "darwin" else 'lungs.ico')
import napari
BUNDLE_ROOT = abspath(join(dirname(napari.__file__), pardir, 'bundle'))

a = Analysis(
    ['../run_exhale.py'],
    pathex=[],
    binaries=[],
    hiddenimports=['pkg_resources.py2_warn', 'importlib', 'freetype', 'stardist'
        ] + collect_submodules("imageio"),
    hooksconfig={"matplotlib": {"backends": "Agg"}},
    runtime_hooks=[],
    datas=copy_metadata('imageio'),
    hookspath=[join(BUNDLE_ROOT, 'hooks'),
        join(dirname(sys.argv[0]), 'hooks')],
    excludes=[
        'FixTk', 'Tkinter',
        'torch', 'nvidia', 'hdf5plugin',
        'pyarrow', 'babel', 'yapf_third_party', 'zmq', 'astroid',
        'sphinx', 'jedi', 'black', 'pycodestype',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

do_splash = True
onefile = False
strip = False

strip = is_linux and strip

if do_splash:
    splash = Splash('exhale_splash.jpg',
                    binaries=a.binaries,
                    datas=a.datas,
                    text_pos=(15, 30),
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
    console=(sys.platform != "darwin"),
    icon=icon_file,
)
#    upx_exclude=[],
#    runtime_tmpdir=None,
#    console=True,
#    disable_windowed_traceback=False,
#    argv_emulation=False,
#    target_arch=None,
#    codesign_identity=None,
#    entitlements_file=None,

if not onefile:
    coll = COLLECT(
        exe,
        *tocoll,
        strip=strip,
        upx=True,
        upx_exclude=[],
        name='exhale',
    )

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name='exhale.app',
        icon=icon_file,
        bundle_identifier='se.maxiv.exhale'
        )
 