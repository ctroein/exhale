#!/usr/bin/env python3
"""
Main entry point for the Exhale GUI.

@author: carl

"""

import os
import shutil
import sys
import traceback
from pathlib import Path

from . import application_description, application_name, application_title, resdir

DESKTOP_ID = "io.github.ctroein.Exhale"


def _splash_text(status):
    return f"{application_title} – {status}"


def _desktop_exec_argument(value):
    """Quote one argument according to the Desktop Entry Exec field rules."""
    value = str(value)
    for character in ("\\", '"', "`", "$"):
        value = value.replace(character, "\\" + character)
    return f'"{value.replace("%", "%%")}"'


def _desktop_command():
    """Return a command which starts this particular EXHALE installation."""
    invoked = Path(sys.argv[0])
    if invoked.name == "exhale":
        if not invoked.is_absolute():
            invoked = Path(shutil.which(str(invoked)) or invoked.absolute())
        return (str(invoked),)
    if invoked.name == "run_exhale.py":
        return (sys.executable, str(invoked.resolve()))
    return (sys.executable, "-m", "exhale")


def _desktop_paths():
    """Return the per-user desktop entry and icon paths."""
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")).expanduser()
    if not data_home.is_absolute():
        raise ValueError("XDG_DATA_HOME must be an absolute path")
    return (
        data_home / "applications" / f"{DESKTOP_ID}.desktop",
        data_home / "icons" / "hicolor" / "512x512" / "apps" / f"{DESKTOP_ID}.png",
    )


def _install_desktop():
    """Register this EXHALE installation with the current user's desktop."""
    desktop_path, icon_path = _desktop_paths()
    command = " ".join(_desktop_exec_argument(part) for part in _desktop_command())
    template = resdir.joinpath("linux", f"{DESKTOP_ID}.desktop").read_text(encoding="utf-8")
    desktop_entry = template.replace("@EXEC@", f"{command} %F")

    desktop_path.parent.mkdir(parents=True, exist_ok=True)
    icon_path.parent.mkdir(parents=True, exist_ok=True)
    desktop_path.write_text(desktop_entry, encoding="utf-8")
    icon_path.write_bytes(resdir.joinpath("icons", "xrf.png").read_bytes())
    print(f"Installed desktop entry: {desktop_path}")


def _remove_desktop():
    """Remove EXHALE's per-user desktop registration, if present."""
    desktop_path, icon_path = _desktop_paths()
    desktop_path.unlink(missing_ok=True)
    icon_path.unlink(missing_ok=True)
    print(f"Removed desktop entry: {desktop_path}")


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
            "-R",
            "--recompile-only",
            action="store_true",
            help="recompile all UI files and exit",
        )
    parser.add_argument(
        "-p", "--project", metavar="DIR", dest="project_dir", help="saved project directory to load"
    )
    parser.add_argument(
        "--startup-check",
        action="store_true",
        help="construct the application and verify runtime imports without opening a window",
    )
    desktop_actions = parser.add_mutually_exclusive_group()
    desktop_actions.add_argument(
        "--install-desktop",
        action="store_true",
        help="register Exhale in the current user's desktop menu and exit",
    )
    desktop_actions.add_argument(
        "--remove-desktop",
        action="store_true",
        help="remove Exhale from the current user's desktop menu and exit",
    )
    parser.add_argument("files", metavar="file", nargs="*", help="initial input files to load")
    parameters = ["project_dir", "files"]

    windowparams = {}
    parser.add_argument("--version", action="version", version=application_title)
    # selmp = multiprocessing.get_start_method(
    #     allow_none=True) is None
    # if selmp:
    #     parser.add_argument('--mpmethod', help="fork, spawn or forkserver")
    args = parser.parse_args()
    windowparams = {k: args.__dict__[k] for k in parameters}
    # if selmp and args.mpmethod:
    #     multiprocessing.set_start_method(args.mpmethod)

    if args.install_desktop or args.remove_desktop:
        if not sys.platform.startswith("linux"):
            parser.error("desktop registration is supported only on Linux")
        if args.install_desktop:
            _install_desktop()
        else:
            _remove_desktop()
        return 0

    # Rebuild UI code on the fly; useful while developing
    if has_ui_files:
        package_dir = os.path.dirname(__file__)
        ui_files = {
            "main_window": package_dir,
            "image_settings_dialog": os.path.join(package_dir, "imaging"),
            "analysis_settings_dialog": os.path.join(package_dir, "analysis"),
            "matrix_export_dialog": os.path.join(package_dir, "analysis"),
            "settings_dialog": package_dir,
        }
        for uif, output_dir in ui_files.items():
            uip = resdir.joinpath("ui", uif + ".ui")
            py = os.path.join(output_dir, uif + "_ui.py")
            if os.path.exists(uip) and (
                args.recompile_only
                or not os.path.exists(py)
                or os.path.getmtime(uip) > os.path.getmtime(py)
            ):
                if args.recompile or args.recompile_only:
                    print(f"Recompiling {uif}")
                    _recompile_ui(uip, py)
                else:
                    print(f"Run with -r to recompile updated {uif} UI file")
        if args.recompile_only:
            return 0

    from qtpy import QtCore, QtGui, QtWidgets

    app = QtWidgets.QApplication.instance()
    if not app:
        #        QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL, True) # why?
        app = QtWidgets.QApplication(sys.argv)
    if sys.platform.startswith("linux"):
        app.setDesktopFileName(DESKTOP_ID)

    qt_splash = None
    if pyi_splash is None and not args.startup_check:
        splash_color = QtGui.QColor("#e0c000")
        pixmap = QtGui.QPixmap(str(resdir.joinpath("xrf_splash.jpg")))
        qt_splash = QtWidgets.QSplashScreen(pixmap)
        splash_font = qt_splash.font()
        splash_font.setBold(True)
        qt_splash.setFont(splash_font)
        qt_splash.showMessage(
            _splash_text("Initializing"),
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignBottom,
            splash_color,
        )
        qt_splash.show()
        exposure_deadline = QtCore.QDeadlineTimer(1000)
        while not exposure_deadline.hasExpired():
            app.processEvents(QtCore.QEventLoop.AllEvents)
            window_handle = qt_splash.windowHandle()
            if window_handle is not None and window_handle.isExposed():
                break
            QtCore.QThread.msleep(1)

    def update_splash(status):
        message = _splash_text(status)
        if pyi_splash is not None:
            pyi_splash.update_text(message)
        elif qt_splash is not None:
            qt_splash.showMessage(
                message,
                QtCore.Qt.AlignLeft | QtCore.Qt.AlignBottom,
                splash_color,
            )
            app.processEvents()

    from . import appearance, icons

    appearance.initialize(QtCore.QSettings("CIPA", application_name))
    if sys.platform != "darwin":
        app.setWindowIcon(icons.icon(icons.IconName.APPLICATION))

    from .main_window import MainWindow

    update_splash("Creating user interface")
    window = MainWindow()

    if args.startup_check:
        import importlib

        from .runtimeinfo import runtime_environment

        importlib.import_module("tensorflow")
        importlib.import_module(f"{__package__}.xrf_refcopy.xrf_utils")
        for name, version in runtime_environment():
            print(f"{name}: {version}")
        window.close()
        app.processEvents()
        if pyi_splash is not None:
            pyi_splash.close()
        print("Startup check passed")
        return 0

    update_splash("Opening")
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
                pyi_splash.update_text(_splash_text("Initializing"))
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
        if pyi_splash is not None:
            try:
                pyi_splash.close()
            except Exception as e:
                print("closing splash failed:", repr(e))
        if "--startup-check" not in sys.argv:
            print("Press enter to quit")
            input()
    sys.exit(res)


if __name__ == "__main__":
    main()
