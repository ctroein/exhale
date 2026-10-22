from PyInstaller.compat import is_linux
from PyInstaller.utils.hooks import collect_data_files


def keep(f):
    if not is_linux and f.endswith(".desktop"):
        return False
    return not any(f.endswith(e) for e in ("~", ".xcf", ".ui"))


datas = [f for f in collect_data_files("exhale", subdir="resources") if keep(f[0])]
