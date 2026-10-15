#!/usr/bin/env python3
"""
Main entry point for the Exhale GUI.

@author: carl

"""

import os
import sys
import traceback

from . import application_description, application_name, application_title, resdir


def _recompile_ui(uipath, pypath):
    "Recompile a single UI XML file into Python"
    import io
    import re

    from qtpy import uic

    buffer = io.StringIO()
    uic.compileUi(uipath, buffer)
    clean_code = re.sub(
        r"^[ \t]*#[^\n]*(generated from|Created by:)[^\n]*\n?",
        "",
        buffer.getvalue(),
        flags=re.MULTILINE,
    )
    clean_code = re.sub(
        r"^[ \t]*from\s+(PyQt|PySide).\b(\s+import\b)",
        r"from qtpy\2",
        clean_code,
        flags=re.MULTILINE,
    )
    with open(pypath, "w", encoding="utf-8") as f:
        f.write(clean_code)


def _run_application(pyi_splash=None):
    "Run the Exhale Qt application"

    import sys

    if sys.platform == "win32":
        # Fix for possible OpenGL problems on Windows
        os.environ.setdefault("QT_OPENGL", "desktop")
        os.environ.setdefault("VISPY_GL_DEBUG", "0")
        # Early load tensorflow because of DLL problems on Windows.
    #        from .xrf_refcopy import xrf_utils

    import argparse
    import signal
    # import multiprocessing

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    has_ui_files = os.path.exists(resdir.joinpath("ui"))
    parser = argparse.ArgumentParser(
        description=(
            f"{application_name}, {application_description}. "
            "Graphical application for processing of XRF lung images."
        )
    )
    if has_ui_files:
        parser.add_argument(
            "-r", "--recompile", action="store_true", help="recompile modified UI files"
        )
    parser.add_argument(
        "-p", "--project", metavar="DIR", dest="project_dir", help="saved project directory to load"
    )
    parser.add_argument("files", metavar="file", nargs="*", help="initial input files to load")
    parameters = ["project_dir", "files"]

    progver = application_title
    windowparams = {}
    parser.add_argument("--version", action="version", version=progver)
    # selmp = multiprocessing.get_start_method(
    #     allow_none=True) is None
    # if selmp:
    #     parser.add_argument('--mpmethod', help="fork, spawn or forkserver")
    args = parser.parse_args()
    windowparams = {k: args.__dict__[k] for k in parameters}
    # if selmp and args.mpmethod:
    #     multiprocessing.set_start_method(args.mpmethod)

    # Rebuild UI code on the fly; useful while developing
    if has_ui_files:
        package_dir = os.path.dirname(__file__)
        ui_files = {
            "main_window": package_dir,
            "image_settings_dialog": os.path.join(package_dir, "imaging"),
            "analysis_settings_dialog": os.path.join(package_dir, "analysis"),
            "settings_dialog": package_dir,
        }
        for uif, output_dir in ui_files.items():
            uip = resdir.joinpath("ui", uif + ".ui")
            py = os.path.join(output_dir, uif + "_ui.py")
            if os.path.exists(uip) and (
                not os.path.exists(py) or os.path.getmtime(uip) > os.path.getmtime(py)
            ):
                if args.recompile:
                    print(f"Recompiling {uif}")
                    _recompile_ui(uip, py)
                else:
                    print(f"Run with -r to recompile updated {uif} UI file")

    from qtpy import QtCore, QtGui, QtWidgets

    app = QtWidgets.QApplication.instance()
    if not app:
        #        QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL, True) # why?
        app = QtWidgets.QApplication(sys.argv)
    from . import appearance, icons

    qt_splash = None
    if pyi_splash is None:
        pixmap = QtGui.QPixmap(str(resdir.joinpath("xrf_splash.jpg")))
        qt_splash = QtWidgets.QSplashScreen(pixmap)
        qt_splash.showMessage(
            f"Initializing {application_title}",
            QtCore.Qt.AlignRight | QtCore.Qt.AlignBottom,
            QtGui.QColor("#e0c000"),
        )
        qt_splash.show()
        exposure_deadline = QtCore.QDeadlineTimer(1000)
        while not exposure_deadline.hasExpired():
            app.processEvents(QtCore.QEventLoop.AllEvents)
            window_handle = qt_splash.windowHandle()
            if window_handle is not None and window_handle.isExposed():
                break
            QtCore.QThread.msleep(1)

    appearance.initialize(QtCore.QSettings("CIPA", application_name))
    if sys.platform != "darwin":
        app.setWindowIcon(icons.icon(icons.IconName.LOGO))

    from .main_window import MainWindow

    window = MainWindow()
    window.show()
    window.post_setup(**windowparams)

    if pyi_splash is not None:
        try:
            pyi_splash.close()
        except Exception as e:
            print("closing splash failed:", repr(e))
            traceback.print_exc()
    elif qt_splash is not None:
        qt_splash.finish(window)

    app.lastWindowClosed.connect(app.quit)
    # app.aboutToQuit.connect(window.cleanup)
    return app.exec_()


def main():
    "Run the Exhale GUI"

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
                pyi_splash.update_text(f"Initializing {application_title}")
            else:
                pyi_splash = None
        except Exception as e:
            pyi_splash = None
            print("pyi_splash failed:", repr(e))
            traceback.print_exc()

    res = 1
    try:
        res = _run_application(pyi_splash)
    except Exception:
        traceback.print_exc()
        print("Press enter to quit")
        if pyi_splash is not None:
            try:
                pyi_splash.close()
            except Exception as e:
                print("closing splash failed:", repr(e))
            # except:
            #     pass
        input()
    sys.exit(res)


if __name__ == "__main__":
    main()
