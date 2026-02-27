#!/bin/bash

pyinstaller -D -n exhale --additional-hooks-dir recipe/hooks run_exhale.py
