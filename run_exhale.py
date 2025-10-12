#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Sep 17 03:28:27 2019

@author: carl
"""

import argparse
from exhalewindow import ExhaleWindow

def main():
    parser = argparse.ArgumentParser(
            description='Graphical application for processing of "\
                "EXHALE lung images.')
    parser.add_argument('files', metavar='file', nargs='*',
                        help='initial input files to load')
    parser.add_argument('-p', '--params', metavar='file.pjs', dest='paramFile',
                        help='parameter file to load')
    ExhaleWindow.run_application(
        parser=parser, parameters=['files', 'paramFile'])

if __name__ == '__main__':
    main()

