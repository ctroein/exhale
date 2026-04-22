# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from os.path import abspath, join, dirname, pardir
from PyInstaller.building.build_main import Analysis, PYZ, EXE, COLLECT, BUNDLE, Splash
from PyInstaller.compat import is_linux
from PyInstaller.utils.hooks import collect_submodules, copy_metadata
import subprocess

# --- version from git (authoritative with setuptools-scm) ---
def get_version():
    try:
        tag = subprocess.check_output(
            ["git", "describe", "--tags", "--abbrev=0"],
            text=True,
        ).strip()
        return tag.lstrip("v")
    except Exception:
        raise RuntimeError("Cannot determine version from git tags")

exhale_version = get_version()
print("Building EXHALE", exhale_version)


res = join(pardir, "exhale", "resources")
datas = [
#    (join(res, "icons", "document-open.svg"), "exhale/resources/icons"),
    (join(res, "models", "2D_versatile_fluo_copy", "*"),
        "exhale/resources/models/2D_versatile_fluo_copy"),
]

if sys.platform == "darwin":
#    datas.append((join(res, "icons", "lungs.icns"), "exhale/resources/icons"))
    icon_file = join("icons", "lungs.icns")
else:
    datas.append((join(res, "icons", "lungs.png"), "exhale/resources/icons"))
    if sys.platform == "win32":
        icon_file = join("icons", "lungs.ico")
    else:
        icon_file = join("icons", "lungs.png")

datas = datas + copy_metadata('imageio')

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
    datas=datas,
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

do_splash = (sys.platform != "darwin")
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
        bundle_identifier='se.lu.cipa.exhale'
        )
