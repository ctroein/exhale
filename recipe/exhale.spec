# -*- mode: python ; coding: utf-8 -*-

import sys
from os.path import abspath, join, dirname, pardir
from PyInstaller.building.build_main import Analysis, PYZ, EXE, COLLECT, BUNDLE
from PyInstaller.utils.hooks import collect_data_files
import napari
import importlib

sys.modules['FixTk'] = None

NAPARI_ROOT = dirname(napari.__file__)
BUNDLE_ROOT = abspath(join(NAPARI_ROOT, pardir, 'bundle'))


def get_version():
    if sys.platform != 'win32':
        return None
    from PyInstaller.utils.win32.versioninfo import (
        VSVersionInfo,
        FixedFileInfo,
        StringFileInfo,
        StringTable,
        StringStruct,
        VarFileInfo,
        VarStruct,
    )
    from datetime import datetime

    ver_str = napari.__version__
    version = ver_str.replace("+", '.').split('.')
    version = [int(p) for p in version if p.isnumeric()]
    version += [0] * (4 - len(version))

    return VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=tuple(version)[:4], prodvers=tuple(version)[:4],
        ),
        kids=[
            StringFileInfo(
                [
                    StringTable(
                        '040904E4',
                        [
                            StringStruct('CompanyName', 'napari'),
                            StringStruct('FileDescription', 'napari'),
                            StringStruct('FileVersion', ver_str),
                            StringStruct('InternalName', 'napari'),
                            StringStruct(
                                'LegalCopyright',
                                f'napari {datetime.now().year}. All rights reserved.',
                            ),
                            StringStruct('OriginalFilename', 'napari.exe'),
                            StringStruct('ProductName', 'napari'),
                            StringStruct('ProductVersion', ver_str),
                        ],
                    )
                ]
            ),
            VarFileInfo([VarStruct(u'Translation', [0x409, 1252])]),
        ],
    )


def keep(x):
    if any(x.endswith(e) for e in ('.DS_Store', '.qrc', '~', '.xcf')):
        return False
    if any(i in x for i in ('.mypy_cache', 'plugins/_tests/fixtures')):
        return False
    return True


#exhdata = [f for f in collect_data_files('exhale', subdir='resources') if keep(f[0])]
#if not exhdata:
#    raise RuntimeError("Missing exhale resources; try pip -install -e .")
#exhdata = []

#import vispy, vispy.glsl, vispy.io
#import fabio

DATA_FILES = (
#    [(os.path.dirname(vispy.glsl.__file__), os.path.join("vispy", "glsl")),
#    (os.path.join(os.path.dirname(vispy.io.__file__), "_data"), os.path.join("vispy", "io", "_data")),
#    (os.path.dirname(freetype.__file__), os.path.join("freetype")),
#    ] +
    [f for f in collect_data_files('napari') if keep(f[0])]
#    exhdata
    )


a = Analysis(
    ['../run_exhale.py'],
    pathex=[],
    binaries=[],
    hiddenimports=(['pkg_resources.py2_warn', 'importlib', 'napari.conftest']
#        + ['fabio.'+c for c,_ in fabio.fabioformats._default_codecs]
#        + ['vispy.ext._bundled.six', 'vispy.app.backends._pyqt5',
#        'freetype'
        ),
    hooksconfig={},
    runtime_hooks=[],
    datas=DATA_FILES,
    hookspath=[join(BUNDLE_ROOT, 'hooks')] +
        [os.path.join(os.path.dirname(sys.argv[0]), 'hooks')],
    excludes=[
        'FixTk',
        'tcl',
        'tk',
        '_tkinter',
        'tkinter',
        'Tkinter',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)


pyz = PYZ(a.pure, a.zipped_data, cipher=None)

#    exclude_binaries=True,

exe = EXE(
    pyz,
    a.scripts,
#    a.binaries,
#    a.datas,
    [],
    exclude_binaries=True,
    name='exhale',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='exhale/resources/lungs.ico',
    splash='exhale/resources/exhale_splash.jpg',
)


coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='exhale',
)
