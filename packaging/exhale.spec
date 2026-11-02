# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from importlib.metadata import distributions
from os.path import abspath, dirname, join
from PyInstaller.building.build_main import Analysis, PYZ, EXE, COLLECT, BUNDLE, Splash
from PyInstaller.compat import is_linux
from PyInstaller.utils.hooks import PY_DYLIB_PATTERNS, collect_dynamic_libs, collect_submodules, copy_metadata
import subprocess

PACKAGING_DIR = abspath(SPECPATH)
ROOT = dirname(PACKAGING_DIR)

def get_version():
    v = os.environ.get("EXHALE_VERSION")
    if v:
        return v.lstrip("v")
    try:
        tag = subprocess.check_output(
            ["git", "describe", "--tags", "--match", "v[0-9]*", "--abbrev=0"],
            text=True, cwd=ROOT,
        ).strip()
        return tag.lstrip("v")
    except Exception:
        raise RuntimeError("Cannot determine version. Set "
            "EXHALE_VERSION or build from a tagged git checkout.")

exhale_version = get_version()
print("Building Exhale", exhale_version)


res = join(ROOT, "exhale", "resources")
datas = [
    (join(res, "models", "2D_versatile_fluo_copy", "*"),
        "exhale/resources/models/2D_versatile_fluo_copy"),
]

if sys.platform == "darwin":
    icon_file = join(PACKAGING_DIR, "icons", "xrf.icns")
else:
    datas.append((join(res, "icons", "xrf.png"), "exhale/resources/icons"))
    if sys.platform == "win32":
        icon_file = join(PACKAGING_DIR, "icons", "xrf.ico")
    else:
        icon_file = join(res, "icons", "xrf.png")

datas = datas + copy_metadata('imageio')
# Include dependency metadata and licenses, including the DINOv3 redistribution license.
datas += copy_metadata('cellpose', recursive=True)
datas += copy_metadata('dinov3', recursive=True)

# Torch 2.15's cuda-toolkit dependency stores versioned libraries under nvidia/cu13.
# Current hooks infer only older nvidia-*-cuXX distribution names, so collect these
# explicitly from the clean build environment, preserving their package layout.
binaries = []
if is_linux:
    binaries = collect_dynamic_libs('nvidia', search_patterns=PY_DYLIB_PATTERNS + ['lib*.so.*'])
    for distribution in distributions():
        name = distribution.metadata.get('Name', '')
        if name.lower().startswith(('nvidia-', 'cuda-')):
            datas += copy_metadata(name)


import napari
BUNDLE_ROOT = abspath(join(dirname(napari.__file__), os.pardir, 'bundle'))

a = Analysis(
    [join(ROOT, "run_exhale.py")],
    pathex=[],
    binaries=binaries,
    hiddenimports=['pkg_resources.py2_warn', 'importlib', 'freetype', 'stardist',
        'cellpose.models', 'dinov3.hub.backbones'
        ] + collect_submodules("imageio"),
    runtime_hooks=[],
    datas=datas,
    hookspath=[join(BUNDLE_ROOT, 'hooks'), join(PACKAGING_DIR, 'hooks')],
    excludes=[
        'FixTk', 'Tkinter',
        'hdf5plugin',
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
    splash = Splash(join(res, 'xrf_splash.jpg'),
                    binaries=a.binaries,
                    datas=a.datas,
                    text_pos=(15, 612),
                    text_size=11,
                    text_color='#e0c000',
                    text_default=f"Exhale {exhale_version} – Starting")

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
