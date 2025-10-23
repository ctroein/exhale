#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Main entry point for EXHALE GUI.

@author: carl

Configuration for Nuitka packaging:
# nuitka-project-if: {OS} in ("Windows"):
#    nuitka-project: --mode=onefile --windows-icon-from-ico=resources/lungs.ico
#    nuitka-project: --onefile-windows-splash-screen-image={MAIN_DIRECTORY}/resources/splash.jpg
# nuitka-project-if: {OS} in ("Linux"):
#    nuitka-project: --mode=standalone --linux-icon=resources/lungs.ico
# nuitka-project: --enable-plugin=pyqt5
# nu itka-project: --include-data-dir=resources=resources

"""

import argparse
from exhalewindow import ExhaleWindow
import tempfile, os

# Use this code to signal the splash screen removal.
if "NUITKA_ONEFILE_PARENT" in os.environ:
   splash_filename = os.path.join(
      tempfile.gettempdir(),
      "onefile_%d_splash_feedback.tmp" % int(os.environ["NUITKA_ONEFILE_PARENT"]),
   )
   if os.path.exists(splash_filename):
      os.unlink(splash_filename)

def main():
    parser = argparse.ArgumentParser(
        description="""EXHALE, Efficient X-ray Hub Aiding Lung Explorations.
            Graphical application for processing of XRF lung images.""")
    parser.add_argument('files', metavar='file', nargs='*',
                        help='initial input files to load')
    parser.add_argument('-p', '--params', metavar='file.pjs', dest='paramFile',
                        help='parameter file to load')
    ExhaleWindow.run_application(
        parser=parser, parameters=['files', 'paramFile'])

if __name__ == '__main__':
    main()

