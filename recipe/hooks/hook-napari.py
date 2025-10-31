from PyInstaller.utils.hooks import collect_data_files

hiddenimports = ['napari.conftest', 'napari_svg']

def keep(x):
    if any(x.endswith(e) for e in ('.DS_Store', '.qrc', '~', '.xcf')):
        return False
    if any(i in x for i in ('.mypy_cache', 'plugins/_tests/fixtures')):
        return False
    return True

datas = [f for f in collect_data_files('napari') if keep(f[0])]

