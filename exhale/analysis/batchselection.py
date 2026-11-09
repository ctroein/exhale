"""Explicit sample-check selection shared by segmentation and clustering dialogs."""

from qtpy import QtCore


def configure_batch_selection(dialog, rows, refresh):
    """Wire All/None/Unprocessed actions for (item, has_result, available) rows.

    These actions change check states directly; they never filter the selected
    jobs behind the user's back. Existing results refer to the dialog's method.
    """
    rows = tuple(rows)

    def select(mode):
        with QtCore.QSignalBlocker(dialog.sampleTree):
            for item, existing, available in rows:
                checked = available and (mode == "all" or (mode == "new" and not existing))
                item.setCheckState(0, QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked)
        refresh()

    dialog.selectAll.clicked.connect(lambda: select("all"))
    dialog.selectNone.clicked.connect(lambda: select("none"))
    dialog.selectNew.clicked.connect(lambda: select("new"))
