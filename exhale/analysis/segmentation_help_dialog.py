"""Scrollable editing instructions independent of the segmentation panel's size."""

from html import escape

from qtpy import QtGui, QtWidgets


class SegmentationHelpDialog(QtWidgets.QDialog):
    """Show editing tools and native keyboard shortcuts without blocking the viewer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editing help")
        layout = QtWidgets.QVBoxLayout(self)
        text = QtWidgets.QTextBrowser(self)
        undo = escape(QtGui.QKeySequence(QtGui.QKeySequence.Undo).toString())
        redo = escape(QtGui.QKeySequence(QtGui.QKeySequence.Redo).toString())
        text.setHtml(f"""
<h3>Getting started</h3>
<p>Choose a mask and open Edit to add missing segments, correct their
 boundaries, or separate segments that were joined.</p>
<p>To annotate without running a segmentation method, select the nuclei channel
 and use <b>Create empty mask</b> beside the Segmentation mask heading.
 This opens an empty mask in Edit with the element map underneath.</p>
<p>Use <b>Select (S)</b> to click the segment you want to change. Ctrl+click adds or
 removes a segment from the selection; clicking the background clears it.
 Shift+drag selects all segments touched by a rectangle. Hold Ctrl as well to
 add them to your selection.</p>
<p>Drag in Select mode to move around the image; use the wheel to zoom.</p>

<h3>Drawing and erasing</h3>
<p><b>Outline (O)</b> creates a segment by drawing around its boundary.
 To change an existing segment, select it first, then hold Shift while starting
 an outline to add the enclosed area, or Ctrl to remove it.
 The line closes when you release the mouse. Going around again in the same
 direction keeps the overlap filled; returning around an inner area in the
 opposite direction leaves it empty.</p>
<p>Enable <b>Fit to features</b> to adjust an approximate outline to the nuclei
 element map when you release the mouse. It favors nearby edges where the
 intensity falls toward the outside of your outline. The distance in pixels limits how far
 the boundary can move inward or outward. Use Undo if the result is unsuitable.</p>
<p><b>Brush draw (B)</b> paints into the selected segment, or creates a new one
 if nothing is selected. <b>Brush erase (E)</b> removes parts of a segment.
 Use the size control to adjust the brush or eraser; each remembers its own size.
 The right mouse button temporarily does the opposite, using that same size.</p>
<p>Leave <b>Protect other segments</b> on to avoid changing unselected segments.</p>
<p>If erasing leaves separate pieces, use <b>Disconnected parts</b> to keep them
 as one segment, split them into separate segments, or be asked which you want.</p>

<h3>Splitting, merging and deleting</h3>
<p><b>Split (X)</b> divides segments along a line you draw. Draw all the way
 through a segment to cut it; one line can cut several segments.
 There is no need to select them first.</p>
<p>To combine segments, select them and use <b>Merge (M)</b>.
 To remove selected segments entirely, use <b>Delete</b>.</p>

<h3>Keeping your changes</h3>
<p>Use <b>Undo ({undo})</b> and <b>Redo ({redo})</b> to revisit your edits.
 Escape cancels an unfinished stroke or selection rectangle.
 The letters beside the tool names are keyboard shortcuts.</p>
<p><b>Accept changes</b> saves your corrections. The first correction of a
 generated mask creates an edited mask and leaves the prediction available.
 Further corrections update that edited mask; manual masks are updated from
 their first acceptance. The name is retained.
 <b>Reject changes</b> discards your current edits.
 Both return to Overview, where you can name or mark the mask as reviewed
 for training.</p>

""")
        layout.addWidget(text)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close, parent=self)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)
        metrics = self.fontMetrics()
        self.resize(metrics.averageCharWidth() * 80, metrics.lineSpacing() * 28)
