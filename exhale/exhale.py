#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Main entry point for EXHALE GUI.

@author: carl

"""

import sys
import traceback
import os
from .appversion import exhale_version


def _run_application(pyi_splash=None):
    "Run the EXHALE Qt application"

    import signal
    import argparse
    import multiprocessing
    from .exhalewindow import ExhaleWindow, resdir
    from silx.gui.qt import Qt, QApplication, QIcon

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

    app = QApplication.instance()
    if not app:
        QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL, True) # why?
        app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(resdir.joinpath("lungs.ico"))))
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
    "Run the EXHALE "

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

