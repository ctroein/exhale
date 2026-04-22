#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Main entry point for EXHALE GUI.

@author: carl

"""

import sys
import traceback
import os
import importlib
from importlib.metadata import version, PackageNotFoundError

try:
    exhale_version = version("exhale")
except PackageNotFoundError:
    exhale_version = "dev"

resdir = importlib.resources.files("exhale").joinpath("resources")

def _run_application(pyi_splash=None):
    "Run the EXHALE Qt application"

    import sys
    if sys.platform == "win32":
        # Fix for possible OpenGL problems on Windows
        os.environ.setdefault("QT_OPENGL", "desktop")
        os.environ.setdefault("VISPY_GL_DEBUG", "0")
        # Early load tensorflow because of DLL problems on Windows.
#        from .xrf_refcopy import xrf_utils

    import signal
    import argparse
    import multiprocessing

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    parser = argparse.ArgumentParser(
        description="""EXHALE, Efficient X-ray Hub Aiding Lung Explorations.
            Graphical application for processing of XRF lung images.""")
    parser.add_argument('files', metavar='file', nargs='*',
                        help='initial input files to load')
    parser.add_argument('-p', '--params', metavar='file.pjs', dest='paramFile',
                        help='parameter file to load')
    parameters=['files', 'paramFile']

    progver = f'Exhale {exhale_version}'
    windowparams = {}
    parser.add_argument('--version', action='version',
                        version=progver)
    selmp = multiprocessing.get_start_method(
        allow_none=True) is None
    if selmp:
        parser.add_argument('--mpmethod', help='')
    args = parser.parse_args()
    windowparams = { k: args.__dict__[k] for k in parameters }
    if selmp and args.mpmethod:
        multiprocessing.set_start_method(args.mpmethod)

    # Rebuild UI code on the fly; useful while developing
    from silx.gui.qt import BINDING
    ui_files = ["exhale_qt", "imagedialog", "analysisdialog"]
    for uif in ui_files:
        uip = resdir.joinpath("ui", uif + ".ui")
        py = os.path.join(os.path.dirname(__file__), uif + ".py")
        if (os.path.exists(uip) and os.path.exists(py) and
            os.path.getmtime(uip) > os.path.getmtime(py)):
            print(f"Recompiling {uif}")
            uic = importlib.import_module(BINDING + ".uic")
            with open(py, 'w', encoding='utf-8') as f:
                uic.compileUi(uip, f)

    from silx.gui.qt import QApplication, QIcon
    app = QApplication.instance()
    if not app:
#        QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL, True) # why?
        app = QApplication(sys.argv)
    if sys.platform != "darwin":
        app.setWindowIcon(QIcon(str(resdir.joinpath("icons/lungs.png"))))

    from .exhalewindow import ExhaleWindow
    window = ExhaleWindow()
    window.show()

    if pyi_splash is not None:
        try:
            pyi_splash.close()
        except Exception as e:
            print("closing splash failed:", repr(e))
            traceback.print_exc()

    window.post_setup(**windowparams)
    app.lastWindowClosed.connect(app.quit);
    app.aboutToQuit.connect(window.cleanup)
    return app.exec_()


def main():
    "Run the EXHALE GUI"

    pyi_splash = None
    # print("startup: frozen?", getattr(sys, "frozen", False))
    # print("startup: _PYI_SPLASH_IPC =", os.environ.get("_PYI_SPLASH_IPC"))
    # print("startup: suppress =",
    #       os.environ.get("PYINSTALLER_SUPPRESS_SPLASH_SCREEN"))
    if "_PYI_SPLASH_IPC" in os.environ:
        try:
            import pyi_splash
            # print("startup: imported pyi_splash")
            # print("startup: is_alive =", pyi_splash.is_alive())
            if pyi_splash.is_alive():
                pyi_splash.update_text(
                    f"Initializing EXHALE {exhale_version}")
        except Exception as e:
            print("pyi_splash failed:", repr(e))
            traceback.print_exc()

    res = 1
    try:
        res = _run_application(pyi_splash)
    except Exception:
        traceback.print_exc()
        print('Press enter to quit')
        if pyi_splash is not None:
            try:
                pyi_splash.close()
            except Exception as e:
                print("closing splash failed:", repr(e))
            # except:
            #     pass
        input()
    sys.exit(res)

if __name__ == '__main__':
    main()

