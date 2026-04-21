from PyInstaller.utils.hooks import collect_data_files
import os.path
import vispy, vispy.glsl, vispy.io

datas = collect_data_files('vispy')
# [(os.path.dirname(vispy.glsl.__file__), os.path.join("vispy", "glsl")),
         # (os.path.join(os.path.dirname(vispy.io.__file__), "_data"), os.path.join("vispy", "io", "_data")),
#    (os.path.dirname(freetype.__file__), os.path.join("freetype")),
        # ] +

hiddenimports=['vispy.ext._bundled.six', 'vispy.app.backends._pyqt5']
#        'freetype'
