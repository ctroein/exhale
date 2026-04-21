from PyInstaller.utils.hooks import collect_data_files

hiddenimports = ['napari.conftest', 'napari_svg']

def keep(x):
    if any(x.endswith(e) for e in ('.DS_Store', '.qrc', '~', '.xcf')):
        return False
    if any(i in x for i in ('.mypy_cache', '_tests')):
        return False
    return True

datas = sum([[f for f in collect_data_files(p) if keep(f[0])]
            for p in ('napari', 'napari_builtins', 'napari_svg')],
            [])

