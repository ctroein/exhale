#!/usr/bin/env python3
"""Resizable dialog for handled and unhandled errors."""

import sys
import traceback

from qtpy import QtCore, QtGui, QtWidgets


class ExceptionDetailsDialog(QtWidgets.QDialog):
    """Reusable modal presentation of an error summary and details."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ExceptionDetailsDialog")
        self.setWindowTitle("Error")
        self.setWindowFlag(QtCore.Qt.WindowContextHelpButtonHint, False)
        self.setSizeGripEnabled(True)
        self.resize(900, 650)
        self.setMinimumSize(700, 500)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.summaryLabel = QtWidgets.QLabel(self)
        self.summaryLabel.setWordWrap(True)
        self.summaryLabel.setTextFormat(QtCore.Qt.PlainText)
        self.summaryLabel.setTextInteractionFlags(
            QtCore.Qt.TextSelectableByMouse
            | QtCore.Qt.TextSelectableByKeyboard
        )
        layout.addWidget(self.summaryLabel)

        self.tracebackEdit = QtWidgets.QPlainTextEdit(self)
        self.tracebackEdit.setReadOnly(True)
        self.tracebackEdit.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        self.tracebackEdit.setFont(font)
        layout.addWidget(self.tracebackEdit, 1)

        self.buttonBox = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Close, parent=self)
        self.buttonBox.rejected.connect(self.reject)
        layout.addWidget(self.buttonBox)

    def set_exception(self, *, title: str, summary: str, details: str) -> None:
        self.setWindowTitle(title)
        self.summaryLabel.setText(summary)
        self.tracebackEdit.setPlainText(details)
        self.tracebackEdit.moveCursor(QtGui.QTextCursor.Start)

    def show_exception(self, *, title: str, summary: str, details: str) -> int:
        self.set_exception(title=title, summary=summary, details=details)
        self.raise_()
        self.activateWindow()
        return self.exec()


class ExceptionDialog:
    @staticmethod
    def install(window):
        """Install a graphical handler for otherwise unhandled exceptions."""
        def ehook(exctype, value, tb):
            summary = "Unhandled exception: " + repr(value)
            details = "".join(traceback.format_exception(exctype, value, tb))
            print(summary, "\n", details)
            window.show_error(summary, details)

        oldhook = sys.excepthook
        sys.excepthook = ehook
        return oldhook
