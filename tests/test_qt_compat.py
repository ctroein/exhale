"""Qt wrapper and UI compiler regressions; run with QT_QPA_PLATFORM=offscreen."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from qtpy import QtGui, QtWidgets, uic

from exhale import resdir
from exhale.__main__ import _recompile_ui
from exhale.listwidgets import ColorButton


class UiCompilerTests(unittest.TestCase):
    def test_compile_all_forms_through_qtpy(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ("exhale_qt", "imagedialog", "analysisdialog"):
                with self.subTest(name=name):
                    output = Path(directory) / (name + ".py")
                    _recompile_ui(str(resdir / "ui" / (name + ".ui")), output)
                    code = output.read_text()
                    self.assertIn("from qtpy import", code)
                    self.assertNotRegex(code, r"from (PyQt|PySide)\d")
                    self.assertNotIn("Created by:", code)
                    self.assertNotIn("generated from", code)
                    compile(code, str(output), "exec")

    def test_rewrites_each_binding_import(self):
        # This checks compiler output rewriting, not runtime binding support.
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "form.py"
            for binding in ("PyQt5", "PyQt6", "PySide2", "PySide6"):
                with self.subTest(binding=binding):
                    def compile_ui(source, buffer):
                        buffer.write(f"# Created by: {binding}\n"
                                     f"from {binding} import QtCore, QtWidgets\n"
                                     "value = 42\n")
                    with patch.object(uic, "compileUi", side_effect=compile_ui):
                        _recompile_ui("unused.ui", output)
                    self.assertEqual(output.read_text(),
                                     "from qtpy import QtCore, QtWidgets\nvalue = 42\n")

    def test_compiler_failure_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "form.py"
            output.write_text("original\n")
            with patch.object(uic, "compileUi", side_effect=ValueError("invalid UI")):
                with self.assertRaises(ValueError):
                    _recompile_ui("unused.ui", output)
            self.assertEqual(output.read_text(), "original\n")


class ColorButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_rgb_rgba_arrays_and_qcolor(self):
        button = ColorButton()
        emitted = []
        button.colorChanged.connect(emitted.append)
        for color in ([0.2, 0.4, 0.6], np.array([0.2, 0.4, 0.6, 0.8]),
                      QtGui.QColor.fromRgbF(0.2, 0.4, 0.6)):
            button.setColor(color)
            np.testing.assert_allclose(button.color(), [0.2, 0.4, 0.6], atol=1/255)
            np.testing.assert_allclose(emitted[-1], button.color())
        button.dialog.deleteLater()
        button.deleteLater()
