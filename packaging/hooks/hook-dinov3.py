"""Collect DINOv3's packaged configurations alongside its Python modules."""

from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("dinov3")
