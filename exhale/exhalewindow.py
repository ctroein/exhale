#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Jan 30 22:33:00 2024

@author: carl
"""

import numpy as np
# from typing import Optional
# from collections.abc import Iterable
from functools import partial
# import importlib
import re
import os
from time import strftime

# Note to users: export QT_API=pyqt5 to force PyQt5 if needed.
import silx
from silx.gui import qt, icons, hdf5
from silx.gui.qt import Qt #, QApplication
# from silx.gui.plot import PlotWidget
from silx.gui.plot.items.core import ItemChangedType
from silx.app.view.DataPanel import DataPanel

from .exceptiondialog import ExceptionDialog
from .overridecursor import OverrideCursor
from .elementsettings import ElementSettings, Normalizers
from .imagesettings import ImageSettings, Layouts, Colorschemes, Scalebars
from .listwidgets import ImageElementBox, ImageHeaderBox
from .listwidgets import ElementListWidget, ImageListWidget
from .imagecomposer import ImageComposer
from .analysisworker import AnalysisWorker
from . import projectio
from .exhale import exhale_version
from .source_refs import ElementRef, LoadedSource, open_source
from .constants import CONCENTRATION_UNITS

from .exhale_qt import Ui_ExhaleWindow
from .imagedialog import Ui_ImageDialog
from .analysisdialog import Ui_AnalysisDialog

_LOAD_NAPARI_EARLY = True

def scale_font(widget: qt.QWidget, scale: float):
    "Rescale font of widget and its children"
    font = widget.font()
    font.setPointSizeF(font.pointSizeF() * scale)
    widget.setFont(font)

class ImageDialog(qt.QDialog, Ui_ImageDialog):
    def __init__(self, parent=None):
        qt.QDialog.__init__(self, parent)
        self.setupUi(self)

class AnalysisDialog(qt.QDialog, Ui_AnalysisDialog):
    def __init__(self, parent=None):
        qt.QDialog.__init__(self, parent)
        self.setupUi(self)

class ExhaleWindow(qt.QMainWindow, Ui_ExhaleWindow):
    "Main window of this thing"
    selectedElementsChanged = qt.Signal() # The set of selected elements changed

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = qt.QSettings('CIPA', 'Exhale')
        # QApplication.instance().installEventFilter(self) # needed why?
        self.setupUi(self)
        self.setWindowTitle(f'Exhale {exhale_version}')

        self.errorMsg = qt.QErrorMessage(self)
        self.errorMsg.setSizeGripEnabled(True)
        self.errorMsg.setWindowModality(Qt.WindowModal)

        imd = ImageDialog()
        self.imageDialog = imd
        self.composeSettings.clicked.connect(imd.show)
        self.composeSettings.clicked.connect(imd.raise_)
        imd.buttonBox.clicked.connect(imd.hide)

        ad = AnalysisDialog()
        self.analysisDialog = ad
        self.analysisOptions.clicked.connect(ad.show)
        self.analysisOptions.clicked.connect(ad.raise_)
        ad.buttonBox.clicked.connect(ad.hide)

        # Make all the dialog input widgets available in self since it's
        # only an UI detail that they're offloaded to a dialog.
        self.composeScalebarColor = imd.composeScalebarColor
        self.composeScalebarBg = imd.composeScalebarBg
        self.composeScalebarBgColor = imd.composeScalebarBgColor
        self.composeScalebar = imd.composeScalebar
        self.composeFontsize = imd.composeFontsize
        self.composeDPI = imd.composeDPI
        self.composePanelLabels = imd.composePanelLabels
        self.composeElementLabels = imd.composeElementLabels
        self.composeElementBorders = imd.composeElementBorders
        self.composeElementLabelsColored = imd.composeElementLabelsColored
        self.composePanelLabelColor = imd.composePanelLabelColor
        self.clusterMinK = ad.clusterMinK
        self.clusterMaxK = ad.clusterMaxK
        self.clusterNInit = ad.clusterNInit
        self.nucleiExpansion = ad.nucleiExpansion
        self.nucleiMinArea = ad.nucleiMinArea

        def themed_icon(*names):
            for name in names:
                icon = None
                try:
                    icon = icons.getQIcon(name)
                except ValueError:
                    ...
                if icon is not None and not icon.isNull():
                    return icon
                icon = qt.QIcon.fromTheme(name)
                if not icon.isNull():
                    return icon
                print("unknown", name)
            return qt.QIcon()

        self.actionOpenFile.setIcon(themed_icon(
            "document-open", "folder-open"))
        self.actionClearFiles.setIcon(themed_icon(
            "edit-clear", "window-close", "close"))
        self.actionLoadProject.setIcon(themed_icon(
            "document-open-recent", "folder-open", "document-open"))
        self.actionSaveProject.setIcon(themed_icon(
            "document-save", "media-floppy"))
        self.actionAbout.setIcon(themed_icon(
            "help-about", "dialog-information", "help"))
        self.actionQuit.setIcon(themed_icon("application-exit"))

        self.actionOpenFile.triggered.connect(self.select_and_open_files)
        self.actionClearFiles.triggered.connect(self.close_all_files)
        self.actionLoadProject.triggered.connect(self.load_project)
        self.actionSaveProject.triggered.connect(self.save_project)
        self.actionAbout.triggered.connect(self.showAbout)
        self.actionQuit.triggered.connect(self.close)

        """
        Main data classes.
            ElementRef identifies one source item, e.g. an HDF5 dataset of TIFF.
            fileSettings maps source_id to LoadedSource.
            elementSettings stores color/settings for materialized elements.
            selectedElements holds checkboxed ElementRefs, available for images.
            currentElement is the currently selected ElementSettings object.
            imageSettings holds settings for all images.
            currentImage is the selected image, exclusive with currentElement.
        """
        self.fileSettings = {} # source_id -> LoadedSource
        self.elementSettings = {} # ElementRef -> ElementSettings
        self.selectedElements = set() # ElementRefs of selected elements
        self.currentElement = None # ElementSettings
        self.imageSettings = {} # id -> ImageSettings
        self.currentImage = None # ImageSettings

        self._create_silx_view()
        self.create_dataTab()
        self.create_analysisTab()
        self.tabWidget.setCurrentIndex(0)


    def confirm_quit(self):
        return qt.QMessageBox.question(
            self, "Quit", "Exit the application?",
            qt.QMessageBox.Yes | qt.QMessageBox.No,
            qt.QMessageBox.No
            ) == qt.QMessageBox.Yes

    def closeEvent(self, ev):
        if not self.confirm_quit():
            ev.ignore()
            return
        self.imageDialog.close()
        self.analysisDialog.close()
        if self._analysisWorker is not None:
            self._analysisWorker.abort()
            self._analysisThread.wait()
        ev.accept()

    def showAbout(self):
        import sys
        import napari

        if hasattr(qt, "PYQT_VERSION_STR"):
            binding_version = qt.PYQT_VERSION_STR
        elif hasattr(qt, "PYSIDE_VERSION_STR"):
            binding_version = qt.PYSIDE_VERSION_STR
        else:
            binding_version = "unknown"

        def imported_version(modname):
            mod = sys.modules.get(modname)
            if mod is not None:
                return getattr(mod, "__version__", "unknown")
            return "(not loaded)"
        qt.QMessageBox.about(
            self,
            "About EXHALE",
            f"""
<h3>EXHALE {exhale_version}</h3>

<p>
EXHALE (Efficient X-ray Hub Aiding Lung Explorations) is part of the
EXHALE project at Lund University and MAX IV,
<a href="https://www.vr.se/english/swecris.html?project=2023-02821_Vinnova#/">
funded by Vinnova</a>.
</p>

<p>
Copyright © 2023–2026 Carl Troein, Tom Delaire, Bryan Falcones,
Emanuel Larsson<br>
Licensed under the MIT License.
</p>

<p>
<b>Runtime environment</b><br>
Python {sys.version.split()[0]}<br>
Qt {qt.QT_VERSION_STR} with {qt.BINDING} {binding_version}<br>
silx {silx.version}<br>
napari {imported_version("napari")}<br>
TensorFlow {imported_version("tensorflow")}<br>
NumPy {np.__version__}<br>
</p>
"""
    )


    def open_file_count(self):
        return sum(1 for fs in self.fileSettings.values() if fs.is_open)

    def source_alias_for_ref(self, ref: ElementRef):
        fs = self.fileSettings.get(ref.source_id)
        return fs.alias if fs is not None else ref.source_id

    def element_display_name(self, ref: ElementRef, *, force_alias=False):
        es = self.elementSettings[ref]
        label = es.name
        if force_alias or self.open_file_count() > 1:
            label = f"{label} ({self.source_alias_for_ref(ref)})"
        fs = self.fileSettings.get(ref.source_id)
        if fs is not None and not fs.is_open:
            label += " [closed]"
        return label

    def element_local_display_name(self, ref):
        source = self.fileSettings.get(ref.source_id)
        orig = (
            source.default_element_name(ref)
            if source is not None
            else ref.item_id.rsplit("/", 1).pop()
        )
        es = self.elementSettings.get(ref)
        if es is not None and es.name != orig:
            return f"{es.name} ({orig})"
        return orig

    # All about the analysis tab

    def create_analysisTab(self):
        "Prepare data analysis tab with Napari viewer"
        self.naparihelper = None
        self._analysisWorker = None
        self._analysisThread = None

        if _LOAD_NAPARI_EARLY:
            self.initialize_analysisTab()
        else:
            def tab_check():
                if (self.tabWidget.currentWidget() == self.analysisTab and
                    self.naparihelper is None):
                    self.initialize_analysisTab()
            self.tabWidget.currentChanged.connect(tab_check)

    def initialize_analysisTab(self):
        "Initialize the data analysis tab; start Napari viewer etc"
        from .naparihelper import NapariHelper
        self.naparihelper = NapariHelper()
        self.naparihelper.set_info_widget(self.analysisInfo)

        self.analysisSplitter.setSizes([180, 400, 200])
        hb = qt.QHBoxLayout()
        hb.setContentsMargins(0, 0, 0, 0)
        hb.addWidget(self.naparihelper.qtwidget, 1)
        self.napariWidget.setLayout(hb)

        scale_font(self.analysisStatus, .8)
        self.selectedElementsChanged.connect(self.update_analysis_channels)
        self.update_analysis_channels()
        self.selectedElementsChanged.connect(self.update_analysis_elements)
        self.update_analysis_elements()
        self.analysisRun.pressed.connect(self.run_analysis)
        def abort_run():
            if self._analysisWorker is not None:
                self._analysisWorker.abort()
        self.analysisAbort.pressed.connect(abort_run)
        self.analysisExport.clicked.connect(self.export_analysis_results)

    def update_analysis_channels(self):
        "Update the comboboxes for nuclei/tissue"
        for dd in (self.analysisChNuclei, self.analysisChTissue):
            ddref = dd.currentData()
            with qt.QSignalBlocker(dd):
                dd.clear()
                dd.addItem("None", None)
                paths = self.selectedElements
                for path in paths:
                    # es = self.elementSettings[path]
                    dd.addItem(self.element_display_name(path), userData=path)
                # Restore previous selections if still present
                for i in range(dd.count()):
                    if dd.itemData(i) == ddref:
                        dd.setCurrentIndex(i)

    def update_analysis_elements(self):
        "Update the list of elements for analysis"
        # For the sake of simplicity, we replace everything
        unsel = set()
        for row in range(self.analysisElements.count()):
            it = self.analysisElements.item(row)
            path = it.data(ElementListWidget.ELEMENT_REF_ROLE)
            if (it.checkState() == Qt.CheckState.Unchecked and
                path in self.selectedElements):
                    unsel.add(path)
        # with qt.QSignalBlocker(self.analysisElements):
        self.analysisElements.clear()
        for path in self.selectedElements:
            # es = self.elementSettings[path]
            self.analysisElements.addElementPath(
                self.element_display_name(path), path, path not in unsel)

    def update_layer_controls(self):
        "Update the layer list in the analysis tab"
        while self.analysisLayerBox.count():
            item = self.analysisLayerBox.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        scale = .8
        for i, h in enumerate(("Layer", "Alpha", "Blend")):
            lab = qt.QLabel(h)
            self.analysisLayerBox.addWidget(lab, 0, i)
            scale_font(lab, scale)
        blends = {"translucent": "Def", "additive": "Add", "minimum": "Min"}
        for i, layer in enumerate(self.naparihelper.viewer.layers):
            row = i + 1
            cb = qt.QCheckBox(layer.name)
            cb.setChecked(layer.visible)
            cb.toggled.connect(lambda checked, lyr=layer:
                               setattr(lyr, "visible", checked))
            scale_font(cb, scale)
            self.analysisLayerBox.addWidget(cb, row, 0)

            alpha = qt.QSpinBox()
            alpha.setRange(0, 100)
            alpha.setValue(int(layer.opacity * 100))
            alpha.valueChanged.connect(lambda val, lyr=layer:
                                       setattr(lyr, "opacity", .01 * val))
            scale_font(alpha, scale)
            self.analysisLayerBox.addWidget(alpha, row, 1)

            blend = qt.QComboBox()
            for bid, bstr in blends.items():
                blend.addItem(bstr, userData=bid)
            blend.currentIndexChanged.connect(
                lambda _, lyr=layer, bl=blend:
                    setattr(lyr, "blending", bl.currentData()))
            scale_font(blend, scale)
            self.analysisLayerBox.addWidget(blend, row, 2)

        # Add a strechable empty row and set the scrollarea width
        self.analysisLayerBox.addWidget(qt.QWidget(), row + 1, 0)
        self.analysisLayerBox.setRowStretch(row + 1, 1)
        w = self.analysisLayerWidget.width()
        self.scrollArea.setMinimumWidth(w)

    def set_analysis_busy(self, busy):
        self.analysisRun.setEnabled(not busy)
        self.analysisChNuclei.setEnabled(not busy)
        self.analysisChTissue.setEnabled(not busy)
        self.analysisProgress.setRange(0, 0 if busy else 1)
        self.clusterMinK.setEnabled(not busy)
        self.clusterMaxK.setEnabled(not busy)
        self.clusterNInit.setEnabled(not busy)
        self.nucleiExpansion.setEnabled(not busy)
        self.nucleiMinArea.setEnabled(not busy)
        self.analysisExport.setEnabled(
            not busy and self.naparihelper.sample is not None)
        self.analysisAbort.setEnabled(busy)

    def run_analysis(self):
        if self._analysisWorker is not None:
            raise RuntimeError("Analysis worker already running")

        def append_status(msg):
            self.analysisStatus.appendPlainText(strftime("[%T] ") + msg)
            self.analysisStatus.ensureCursorVisible()

        self.analysisStatus.clear()
        append_status("Initializing")

        dds = (self.analysisChNuclei, self.analysisChTissue)
        ddrefs = [dd.currentData() for dd in dds]
        if None in ddrefs:
            self.errorMsg.showMessage(
                "Select channels for nuclei and tissue first.")
            return

        # if ddrefs[0] == ddrefs[1]:
        #     self.errorMsg.showMessage(
        #         "Nuclei and tissue channels must differ.")
        #     return
        element_refs = [
            it.data(ElementListWidget.ELEMENT_REF_ROLE)
            for it in (self.analysisElements.item(row)
                       for row in range(self.analysisElements.count()))
            if it.checkState() == Qt.CheckState.Checked]

        thread = qt.QThread(self)
        worker = AnalysisWorker(
            *(self.elementSettings[ddp] for ddp in ddrefs),
            [self.elementSettings[ep] for ep in element_refs],
            nuclei_expansion_px=self.nucleiExpansion.value(),
            nuclei_min_area=self.nucleiMinArea.value(),
            cluster_min_k=self.clusterMinK.value(),
            cluster_max_k=self.clusterMaxK.value(),
            cluster_n_init=self.clusterNInit.value())
        worker.moveToThread(thread)
        worker.progress.connect(append_status)

        def worker_cleanup():
            self._analysisWorker.deleteLater()
            self._analysisWorker = None
            self._analysisThread.quit()
            self._analysisThread = None
            self.set_analysis_busy(False)

        @qt.Slot()
        def on_finished(sample):
            append_status("Rendering results")
            self.naparihelper.set_sample(sample)
            self.update_layer_controls()
            worker_cleanup()
            append_status("Done")

        @qt.Slot()
        def on_failed(details):
            if details == "":
                append_status("Interrupted")
            else:
                append_status("Failed")
                self.errorMsg.showMessage("<pre>"+details+"</pre>")
            worker_cleanup()

        self.set_analysis_busy(True)
        worker.finished.connect(on_finished)
        worker.failed.connect(on_failed)
        thread.started.connect(worker.run)
        # thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.destroyed.connect(lambda: print("Thread object deleted"))
        worker.destroyed.connect(lambda: print("Worker deleted"))
        self._analysisWorker = worker
        self._analysisThread = thread
        thread.start()

    def export_analysis_results(self):
        sample = self.naparihelper.sample
        if sample is None:
            return
        directory = qt.QFileDialog.getExistingDirectory(
            self, "Choose export directory",
            self.settings.value("AnalysisExportDir", ""))
        if not directory:
            return
        self.settings.setValue("AnalysisExportDir", directory)

        try:
            out = sample.export_results(directory)
        except Exception as e:
            self.errorMsg.showMessage(f"Export failed:\n{e}")
            return
        qt.QMessageBox.information(self, "Export complete",
            f"Analysis results exported to:\n{out}")


    # All about the data/elements/images tab

    def loadedFileChanged(self):
        "Update what source is shown in the UI"
        source = self.loadedFileComboBox.currentData()

        with qt.QSignalBlocker(self.loadedFileAlias):
            if source is None:
                self.loadedFileAlias.clear()
                self.loadedFileAlias.setEnabled(False)
            else:
                fs = self.fileSettings.get(source.source_id)
                self.loadedFileAlias.setText(
                    fs.alias if fs is not None else source.alias)
                self.loadedFileAlias.setEnabled(fs is not None)

        self.elementList.clear()
        if source is None:
            return

        for candidate in source.list_elements():
            ref = candidate.ref
            checked = ref in self.selectedElements
            label = (
                self.element_local_display_name(ref)
                if ref in self.elementSettings
                else candidate.name
            )
            self.elementList.addElementPath(label, ref, checked=checked)

    def setImageControlsEnabled(self, enabled : bool):
        "Enable/disable inputs that are relevant to composing an image"
        for o in [self.composeLayoutCB, self.composeColors, self.composeSave,
                  self.composeSettings, self.composeScalebar,
                  self.composeScalebarColor, self.composeScalebarBg,
                  self.composeScalebarBgColor, self.composeElementBorders]:
            o.setEnabled(enabled)
        self.imageHeaderBox.setWidgetsEnabled(enabled)
        for box in self.imageElementBoxes:
            box.setWidgetsEnabled(enabled)
        self.elementHistogramPlot.setHidden(not enabled)


    def setElementControlsEnabled(self, enabled : bool):
        "Enable/disable inputs that are relevant to elementsettings"
        self.elementName.setEnabled(enabled)
        self.elementNormalizer.setEnabled(enabled)
        self.elementNormalizeMin.setEnabled(enabled)
        self.elementNormalizeMax.setEnabled(enabled)
        self.gammaValue.setEnabled(enabled)
        self.elementPercButton.setEnabled(enabled)
        self.elementSDButton.setEnabled(enabled)
        self.elementHistogramPlot.setEnabled(enabled)

    def updateElementNormalizer(self):
        "Hide/show gamma correction and update histogram logscaleness"
        es = self.currentElement
        bins = 256
        if es.normalizer == Normalizers.LOG:
            bins = np.geomspace(es.minPositive, es.dataRange[1], bins + 1)
        hist, edges = np.histogram(es.data, bins=bins, range=es.dataRange)
        self.elementHistogramPlot.getHistogram().setData(
            hist, edges, baseline=0, copy=False)
        isgamma = es.normalizer == Normalizers.GAMMA
        self.gammaLabel.setHidden(not isgamma)
        self.gammaValue.setHidden(not isgamma)
        self.elementHistogramPlot.getXAxis().setScale(
            'log' if es.normalizer == Normalizers.LOG else 'linear')
        self.elementHistogramPlot.resetZoom()

    def updateElementPlot(self):
        "Replot the data after transformation change"
        if es := self.currentElement:
            # Update existing element image, flipped to be consistent
            self.elementPlot.addImage(es.transformedData()[::-1], legend='e',
                                      resetzoom=False, copy=False)

    def showCurrentElement(self):
        "Enable and update the input fields with currentElement data"
        es = self.currentElement
        self.setElementControlsEnabled(True)
        with qt.QSignalBlocker(self.elementNormalizer):
            self.elementNormalizer.setCurrentIndex(es.normalizer.value)
        with qt.QSignalBlocker(self.elementName):
            self.elementName.setText(es.name)
        with qt.QSignalBlocker(self.gammaValue):
            self.gammaValue.setValue(es.gamma)
        for mm in range(2):
            with qt.QSignalBlocker(self.elementNormalizeRange[mm]):
                self.elementNormalizeRange[mm].setRange(*es.dataRange)
                self.elementNormalizeRange[mm].setValue(es.trfRange[mm])

        self.updateElementNormalizer()
        self.elementHistogramPlot.remove(kind='marker')
        self.elementHistogramMarkers = (
            self.elementHistogramPlot.addXMarker(
                es.trfRange[0], text="Min", color='#0000a0',
                draggable=True, constraint=es.minConstraint),
            self.elementHistogramPlot.addXMarker(
                es.trfRange[1], text="Max", color='#0000a0',
                draggable=True, constraint=es.maxConstraint))
        def marker_ch(mm, ict):
            if ict != ItemChangedType.POSITION:
                return
            es.setMinmax(mm, self.elementHistogramMarkers[mm].getXPosition())
            self.elementNormalizeRange[mm].setValue(es.trfRange[mm])
            self.updateElementPlot()
        for mm in range(2):
            self.elementHistogramMarkers[mm].sigItemChanged.connect(
                partial(marker_ch, mm))
        # Replace any other image
        self.elementPlot.addImage(es.transformedData()[::-1], legend='e',
                                  replace=True, copy=False)
        self._composeMeta = None

    def editElement(self, elementref):
        "Big UI update when an element is selected for editing"
        # The element should already have settings at this point
        es = self.elementSettings[elementref]
        self.currentElement = es
        self.currentImage = None
        with qt.QSignalBlocker(self.imageList):
            self.imageList.setCurrentRow(-1)
        self.setImageControlsEnabled(False)
        self.showCurrentElement()

    def storeImageSettings(self, im : ImageSettings):
        "Copy settings from UI to object"
        im.setColorscheme(Colorschemes(self.composeColors.currentIndex()))
        im.setLayout(Layouts(self.composeLayoutCB.currentIndex()))
        im.setScalebar(Scalebars(self.composeScalebar.currentIndex()))
        im.setResolution(self.resolutionValue.value(),
                         self.resolutionUnits.currentText())
        im.setScalebarColors(
            self.composeScalebarColor.color(),
            self.composeScalebarBgColor.color(),
            .5 if self.composeScalebarBg.isChecked() else None)
        im.setFontsize(self.composeFontsize.value())
        im.setDPI(self.composeDPI.value())
        im.setLabels(self.composePanelLabels.isChecked(),
                     self.composeElementLabels.isChecked())
        im.setPanelLabelColor(self.composePanelLabelColor.color())
        im.setElementBorders(self.composeElementBorders.isChecked())
        im.setElementLabelsColored(self.composeElementLabelsColored.isChecked())

    def createImage(self, name):
        "Add the named composed image to the list of images (and display it?)"
        num = max(self.imageSettings.keys()) + 1 if self.imageSettings else 1
        im = ImageSettings(name)
        self.storeImageSettings(im)
        self.imageSettings[num] = im
        self.imageList.addImage(num, im)

    def updateComposedImage(self):
        "Recompute and replace/draw the composed image"
        if im := self.currentImage:
            assert self.currentElement is None
            self.imageComposer.plot_composed_image(self.elementPlot, im)

    def updatePickerColors(self):
        "Update the image element color pickers from the current image"
        for i, c in enumerate(self.currentImage.colors()):
            box = self.imageElementBoxes[i]
            with qt.QSignalBlocker(box):
                box.setColor(c)

    def showComposedImage(self, imgnum):
        "Update what composed image is shown"
        im = self.imageSettings[imgnum]
        self.currentImage = im
        self.currentElement = None
        self.elementList.setCurrentRow(-1)
        self.setImageControlsEnabled(True)
        self.setElementControlsEnabled(False)

        with qt.QSignalBlocker(self.composeLayoutCB):
            self.composeLayoutCB.setCurrentIndex(im.layout.value)
        with qt.QSignalBlocker(self.composeColors):
            self.composeColors.setCurrentIndex(im.colorscheme.value)
        with qt.QSignalBlocker(self.composeScalebar):
            self.composeScalebar.setCurrentIndex(im.scalebar.value)
        with qt.QSignalBlocker(self.composeScalebarColor):
            self.composeScalebarColor.setColor(im.scalebarColor)
        with qt.QSignalBlocker(self.composeScalebarBgColor):
            self.composeScalebarBgColor.setColor(im.scalebarBgColor)
        with qt.QSignalBlocker(self.composeScalebarBg):
            self.composeScalebarBg.setChecked(im.scalebarBgAlpha is not None)
        with qt.QSignalBlocker(self.composeFontsize):
            self.composeFontsize.setValue(im.fontsize)
        with qt.QSignalBlocker(self.composeDPI):
            self.composeDPI.setValue(im.dpi)
        with qt.QSignalBlocker(self.composePanelLabels):
            self.composePanelLabels.setChecked(im.panelLabels)
        with qt.QSignalBlocker(self.composeElementLabels):
            self.composeElementLabels.setChecked(im.elementLabels)
        with qt.QSignalBlocker(self.composePanelLabelColor):
            self.composePanelLabelColor.setColor(im.panelLabelColor)
        with qt.QSignalBlocker(self.composeElementBorders):
            self.composeElementBorders.setChecked(im.elementBorders)
        with qt.QSignalBlocker(self.composeElementLabelsColored):
            self.composeElementLabelsColored.setChecked(
                im.elementLabelsColored)
        with qt.QSignalBlocker(self.imageHeaderBox):
            self.imageHeaderBox.setColor(im.borderColor)
            self.imageHeaderBox.border.setValue(im.borderWidth)
        self.updatePickerColors()

        # Find the corrent index for each dropdown
        for i, box in enumerate(self.imageElementBoxes):
            ix = 0
            if i in im.elements:
                es = im.elements[i]
                # Search through the combo, but we could maintain the
                # order as in selectedElements or something
                for j in range(1, box.combo.count()):
                    if box.combo.itemData(j) == es.ref:
                        ix = j
                        break
            with qt.QSignalBlocker(box.combo):
                box.combo.setCurrentIndex(ix)

    def refresh_element_display_names(self):
        self.loadedFileChanged()
        self.update_analysis_channels()
        self.update_analysis_elements()

        for box in self.imageElementBoxes:
            combo = box.combo
            current = combo.currentData()
            for row in range(1, combo.count()):
                ref = combo.itemData(row)
                if ref in self.elementSettings:
                    combo.setItemText(row, self.element_display_name(ref))
            if current is not None:
                ix = combo.findData(current)
                if ix >= 0:
                    combo.setCurrentIndex(ix)

    def create_dataTab(self):
        "Set up everything in the elements/images tab"

        self.loadFileButton.clicked.connect(self.select_and_open_files)
        self.clearFilesButton.clicked.connect(self.close_all_files)
        self.loadedFileComboBox.currentIndexChanged.connect(
            self.loadedFileChanged)

        def loaded_file_alias_changed():
            source = self.loadedFileComboBox.currentData()
            if source is None:
                return
            fs = self.fileSettings.get(source.source_id)
            if fs is not None:
                fs.alias = self.loadedFileAlias.text()
                source.alias = fs.alias
                self.refresh_element_display_names()
        self.loadedFileAlias.textEdited.connect(loaded_file_alias_changed)

        def ensure_exists(ref):
            "Create element settings if needed"
            if ref not in self.elementSettings:
                source = self.fileSettings[ref.source_id]
                if not source.is_open:
                    raise RuntimeError(
                        "Attempting to access closed file " + ref.source_id)
                data = source.load_array(ref)
                name = source.default_element_name(ref)
                es = ElementSettings(ref=ref, name=name, data=data)
                self.elementSettings[ref] = es

        def select_element(item : qt.QListWidgetItem):
            "Element is selected for use (has been checkboxed)"
            item.setCheckState(Qt.CheckState.Checked)
            ref = item.data(ElementListWidget.ELEMENT_REF_ROLE)
            if ref is None:
                raise TypeError(f"Missing ElementRef in item '{item.text()}'")
            ensure_exists(ref)
            self.selectedElements.add(ref)
            self.selectedElementsChanged.emit()
        el = self.elementList
        el.itemActivated.connect(select_element)

        def deselect_element(item):
            "Element is deselected for use (checkbox was unchecked)"
            item.setCheckState(Qt.CheckState.Unchecked)
            ref = item.data(ElementListWidget.ELEMENT_REF_ROLE)
            self.selectedElements.discard(ref)
            self.selectedElementsChanged.emit()
        el.itemUnwanted.connect(deselect_element)

        def check_element(item : qt.QListWidgetItem):
            "React if item checkbox status has changed"
            if item.checkState() == Qt.CheckState.Checked:
                select_element(item)
            else:
                deselect_element(item)
        el.itemChanged.connect(check_element)

        def curr_elem(curr, prev):
            "Current element set; update the view"
            if curr is not None:
                ref = curr.data(ElementListWidget.ELEMENT_REF_ROLE)
                ensure_exists(ref)
                self.editElement(ref)
        el.currentItemChanged.connect(curr_elem)

        def el_name_ch():
            "Current element name was changed"
            if not (es := self.currentElement):
                return
            es.name = self.elementName.text()
            if self.currentImage is not None:
                # Currently adjusting settings for an element in image
                self.updateComposedImage()
                return
            # Editing the global element: propagate name to copies in images
            for im in self.imageSettings.values():
                for ies in im.elements.values():
                    if ies.ref == es.ref:
                        ies.name = es.name

            for row in range(self.elementList.count()):
                it = self.elementList.item(row)
                if it.data(ElementListWidget.ELEMENT_REF_ROLE) == es.ref:
                    it.setText(self.element_local_display_name(es.ref))
                    break
            self.refresh_element_display_names()
        self.elementName.editingFinished.connect(el_name_ch)

        def norm_ch():
            "Normalization type updated"
            if es := self.currentElement:
                es.normalizer = Normalizers(
                    self.elementNormalizer.currentIndex())
                self.updateElementNormalizer()
                self.updateElementPlot()
        for t in Normalizers:
            self.elementNormalizer.addItem(t.description)
        self.elementNormalizer.currentIndexChanged.connect(norm_ch)

        def gamma_ch():
            "Gamma value changed"
            if es := self.currentElement:
                es.gamma = self.gammaValue.value()
                self.updateElementPlot()
        self.gammaValue.valueChanged.connect(gamma_ch)

        def trf_range_ch(mm, isperc):
            "Normalization (transformation) range changed"
            if es := self.currentElement:
                es.setMinmax(mm, self.elementNormalizeRange[mm].value())
                self.elementNormalizeRange[mm].setValue(es.trfRange[mm])
                # self.elementTransformP[mm].setValue(es.percent(mm))
                with qt.QSignalBlocker(self.elementNormalizeRange[mm]):
                    self.elementHistogramMarkers[mm].setPosition(
                        es.trfRange[mm], None)
        self.elementNormalizeRange = [self.elementNormalizeMin,
                                      self.elementNormalizeMax]
        for mm in range(2):
            self.elementNormalizeRange[mm].valueChanged.connect(
                partial(trf_range_ch, mm, False))

        def mm_button(mode):
            if es := self.currentElement:
                es.setMinmaxByMode(mode)
                self.elementNormalizeRange[0].setValue(es.trfRange[0])
                self.elementNormalizeRange[1].setValue(es.trfRange[1])
                self.updateElementPlot()
        self.elementSDButton.clicked.connect(partial(mm_button, 'sd'))
        self.elementPercButton.clicked.connect(partial(mm_button, 'percent'))

        # Initialize histogram plot
        self.elementHistogramPlot.setKeepDataAspectRatio(False)
        self.elementHistogramPlot.setAxesDisplayed(False)
        self.elementHistogramPlot.setDataMargins(.01, .03, .01, .01)
        self.elementHistogramPlot.setInteractiveMode('pan')
        self.elementHistogramPlot.addHistogram(
            [0], [1, 100], color='gray', fill=True, baseline=0, copy=False)
        self.elementHistogramMarkers = None

        self.elementPlot.setKeepDataAspectRatio(True)
        self.elementPlot.setAxesDisplayed(False)

        def im_element_show(elementnum = -1):
            "Display/adjust an image-element or the whole composed image"
            if im := self.currentImage:
                if es := im.elements.get(elementnum):
                    self.currentElement = es
                    self.showCurrentElement()
                else:
                    if self.currentElement:
                        self.currentElement = None
                        self.setElementControlsEnabled(False)
                    self.updateComposedImage()
                    with qt.QSignalBlocker(self.imageElementButtonGroup):
                        self.imageHeaderBox.edit.setChecked(True)

        def im_element_ch(elementnum, index):
            "An image-element dropdown selection changed"
            if im := self.currentImage:
                box = self.imageElementBoxes[elementnum]
                if index == 0: # Unset?
                    im.setElement(elementnum, None)
                else:
                    ref = box.combo.itemData(index)
                    ensure_exists(ref)
                    im.setElement(elementnum, self.elementSettings[ref])
                im_element_show(-1) # Show image, not image-elements

        def im_color_ch(elementnum, color):
            "An image-element color changed"
            if im := self.currentImage:
                im.setColor(elementnum, color)
                with qt.QSignalBlocker(self.composeColors):
                    self.composeColors.setCurrentIndex(im.colorscheme.value)
                im_element_show(-1)

        def im_border_w_ch(val):
            "Current image border width changed"
            if im := self.currentImage:
                im.setBorderWidth(val)
                im_element_show(-1)
        def im_border_c_ch(color):
            "Current image border color changed"
            if im := self.currentImage:
                im.setBorderColor(color)
                im_element_show(-1)

        self.imageElementButtonGroup = qt.QButtonGroup(self)
        box = ImageHeaderBox()
        self.imageElementBox.addLayout(box)
        self.imageElementButtonGroup.addButton(box.edit, -1)
        box.border.valueChanged.connect(im_border_w_ch)
        box.colorChanged.connect(im_border_c_ch)
        self.imageHeaderBox = box
        self.imageElementBoxes = []
        for i in range(ImageSettings.MAX_ELEMENTS):
            box = ImageElementBox(Colorschemes(0).colors()[i])
            self.imageElementBoxes.append(box)
            self.imageElementBox.addLayout(box)
            self.imageElementButtonGroup.addButton(box.edit, i)
            box.combo.currentIndexChanged.connect(
                partial(im_element_ch, i))
            box.colorChanged.connect(partial(im_color_ch, i))

        # Disable after all things have been created
        self.setImageControlsEnabled(False)
        self.setElementControlsEnabled(False)

        def edit_image_element():
            "Display/adjust image element or composed image"
            if self.currentImage is None:
                return
            elnum = self.imageElementButtonGroup.checkedId()
            im_element_show(elnum)
        self.imageElementButtonGroup.buttonClicked.connect(edit_image_element)

        def add_img():
            "Add new image"
            self.createImage("New image")
        self.addImageButton.clicked.connect(add_img)

        def del_img():
            "Delete current image"
            it = self.imageList.currentItem()
            if not it:
                return
            num = it.data(ImageListWidget.IMG_NUM_ROLE)
            im = self.imageSettings[num]
            ans = qt.QMessageBox.question(
                self, "Delete image",
                f"Do you want to delete image '{im.name}'?")
            if ans == qt.QMessageBox.StandardButton.Yes:
                self.elementPlot.clear()
                del self.imageSettings[num]
                self.currentImage = None
                # Delete last, if new image is selected
                self.imageList.takeItem(self.imageList.row(it))
                # No current image; disable UI components
                # self.setImageControlsEnabled(False)
                # self.elementPlot.clear()
        self.deleteImageButton.clicked.connect(del_img)

        def rename_img(item):
            "Image name modified in list"
            num = item.data(ImageListWidget.IMG_NUM_ROLE)
            if num in self.imageSettings:
                self.imageSettings[num].name = item.text()
        self.imageList.itemChanged.connect(rename_img)

        def layout_ch():
            "Image layout update"
            if im := self.currentImage:
                im.setLayout(Layouts(self.composeLayoutCB.currentIndex()))
                im_element_show(-1)
        self.composeLayoutCB.currentIndexChanged.connect(layout_ch)
        for t in Layouts:
            self.composeLayoutCB.addItem(t.description)

        def colors_ch():
            "Color scheme update"
            if im := self.currentImage:
                im.setColorscheme(Colorschemes(
                    self.composeColors.currentIndex()))
                im_element_show(-1)
                self.updatePickerColors()
        self.composeColors.currentIndexChanged.connect(colors_ch)
        for c in Colorschemes:
            self.composeColors.addItem(c.description)

        def scalebar_ch():
            "Scalebar settings update"
            if im := self.currentImage:
                self.storeImageSettings(im)
                im_element_show(-1)
        self.composeScalebarColor.colorChanged.connect(scalebar_ch)
        self.composeScalebarBgColor.colorChanged.connect(scalebar_ch)
        self.composeScalebarBg.toggled.connect(scalebar_ch)
        for s in Scalebars:
            self.composeScalebar.addItem(s.description)
        # For now we're lazy here: All settings changes trigger store+redraw
        self.composeScalebar.currentIndexChanged.connect(scalebar_ch)
        self.composeFontsize.valueChanged.connect(scalebar_ch)
        self.composeDPI.valueChanged.connect(scalebar_ch)
        self.composePanelLabels.toggled.connect(scalebar_ch)
        self.composeElementLabels.toggled.connect(scalebar_ch)
        self.composeElementBorders.toggled.connect(scalebar_ch)
        self.composeElementLabelsColored.toggled.connect(scalebar_ch)
        self.composePanelLabelColor.colorChanged.connect(scalebar_ch)
        self.resolutionValue.valueChanged.connect(scalebar_ch)
        self.resolutionUnits.currentIndexChanged.connect(scalebar_ch)

        def sel_img(curr, prev):
            "Active image changed"
            if curr is not None:
                self.showComposedImage(
                    curr.data(ImageListWidget.IMG_NUM_ROLE))
                im_element_show(-1)
        self.imageList.currentItemChanged.connect(sel_img)

        self.imageComposer = ImageComposer()
        def mouse_over_plot(event):
            if event["event"] == "mouseMoved":
                if not (im := self.currentImage):
                    return
                ixy = self.imageComposer.map_coordinates(
                    self.elementPlot, event["x"], event["y"])
                if ixy is None:
                    qt.QToolTip.hideText()
                    return
                ix, iy = ixy
                info = f"Pos ({ix}, {iy}):\n" + "\n".join(
                    [f"{el.name}: {el.data[iy, ix]:.4g} {CONCENTRATION_UNITS}"
                     for el in im.elements.values()
                     if iy < el.data.shape[0] and ix < el.data.shape[1]])
                qt.QToolTip.showText(
                    qt.QCursor.pos(), info, self.elementPlot)
        self.elementPlot.sigPlotSignal.connect(mouse_over_plot)

        def save_im():
            if not (im := self.currentImage):
                return
            filters = ImageComposer.get_format_filters()
            filename = self.askFileName(
                title="Save composed image", filter=";;".join(filters),
                settingname="ImageDir", save=True,
                defaultfilename=im.name+".png")
            if filename is not None:
                self.imageComposer.compose(im, filename)
        self.composeSave.clicked.connect(save_im)

        def sync_settings_and_compose():
            "Bring selectedElements, elementList, dropdowns in sync"
            for row in range(self.elementList.count()):
                it = self.elementList.item(row)
                if it.checkState() == Qt.CheckState.Checked:
                    ref = it.data(ElementListWidget.ELEMENT_REF_ROLE)
                    if ref not in self.selectedElements:
                        print(f"Internal error: checked element {it.text()} "
                              "missing from list of selected elements")
                        ensure_exists(ref)
                        self.selectedElements.add(ref)

            for i, box in enumerate(self.imageElementBoxes):
                combo = box.combo
                currefs = set()
                # Iterate from end but skip number 0 (no element)
                for row in range(combo.count() - 1, 0, -1):
                    ref = combo.itemData(row)
                    if ref not in self.selectedElements:
                        combo.removeItem(row)
                    else:
                        label = self.element_display_name(ref)
                        if combo.itemText(row) != label:
                            combo.setItemText(row, label)
                        currefs.add(ref)
                for ref in self.selectedElements:
                    if ref not in currefs:
                        combo.addItem(self.element_display_name(ref),
                                      userData=ref)
        el.model().dataChanged.connect(sync_settings_and_compose)
        self.selectedElementsChanged.connect(sync_settings_and_compose)

        # Set everything up before creating the initial image
        # Don't call createImage because we want the default values this once.
        im = ImageSettings("Untitled")
        self.imageSettings[1] = im
        with qt.QSignalBlocker(self.imageList):
            self.imageList.addImage(1, im)


    ## Begin Silx viewer stuff

    def _create_silx_view(self):
        "Create widgets for the HDF5 exploration tab"
        treeView = hdf5.Hdf5TreeView(self)
        treeModel = hdf5.Hdf5TreeModel(treeView, ownFiles=False)
        self._treeView = treeView
        self._treeModel = treeModel

        toolbar = qt.QToolBar(self)
        toolbar.setIconSize(qt.QSize(16, 16))
        toolbar.setStyleSheet("QToolBar { border: 0px }")
        toolbar.addAction(self.actionOpenFile)

        action = qt.QAction("Close file", toolbar)
        action.setIcon(icons.getQIcon("close"))
        action.setToolTip("Close current file(s)")
        action.triggered.connect(self.close_files_silxview)
        toolbar.addAction(action)

        toolbar.addSeparator()

        action = qt.QAction(toolbar)
        action.setIcon(icons.getQIcon("tree-expand-all"))
        action.setText("Expand all")
        action.setToolTip("Expand all selected items")
        action.triggered.connect(self._expandAllSelected)
        action.setShortcut(qt.QKeySequence(qt.Qt.CTRL | qt.Qt.Key_Plus))
        toolbar.addAction(action)
        treeView.addAction(action)

        action = qt.QAction(toolbar)
        action.setIcon(icons.getQIcon("tree-collapse-all"))
        action.setText("Collapse all")
        action.triggered.connect(self._collapseAllSelected)
        action.setShortcut(qt.QKeySequence(qt.Qt.CTRL | qt.Qt.Key_Minus))
        toolbar.addAction(action)
        treeView.addAction(action)

        treeView.setSelectionMode(treeView.ExtendedSelection)
        treeView.activated.connect(self.displaySelectedData)
        treeModel.setDatasetDragEnabled(True)
        treeView.setModel(treeModel)
        treeView.setSizePolicy(qt.QSizePolicy.Preferred,
                               qt.QSizePolicy.Preferred)
        treeView.header().setStretchLastSection(True)
        treeView.header().resizeSections(qt.QHeaderView.ResizeToContents)

        columns = list(treeModel.COLUMN_IDS)
        columns.remove(treeModel.VALUE_COLUMN)
        columns.remove(treeModel.NODE_COLUMN)
        columns.remove(treeModel.DESCRIPTION_COLUMN)
        columns.insert(3, treeModel.DESCRIPTION_COLUMN)
        treeView.header().setSections(columns)

        # Lay out the explorer and viewer
        treewidget = qt.QWidget(self)
        layout = qt.QVBoxLayout(treewidget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.addWidget(toolbar)
        layout.addWidget(treeView)

        self._dataPanel = DataPanel(self)

        split = qt.QSplitter(self)
        split.setHandleWidth(2)
        split.addWidget(treewidget)
        split.addWidget(self._dataPanel)
        split.setStretchFactor(1, 2)
        split.setCollapsible(0, False)
        split.setCollapsible(1, False)

        tablayout = qt.QVBoxLayout()
        tablayout.setContentsMargins(0, 0, 0, 0)
        tablayout.addWidget(split)
        self.silxTab.setLayout(tablayout)
        return layout

    def displaySelectedData(self):
        """Called to update the dataviewer with the selected data.
        """
        selected = list(self._treeView.selectedH5Nodes(
            ignoreBrokenLinks=False))
        if len(selected) == 1:
            # Update the viewer for a single selection
            self._dataPanel.setData(selected[0])

    def _expandAllSelected(self):
        """Expand all selected items of the tree.

        The depth is fixed to avoid infinite loop with recurssive links.
        """
        with OverrideCursor():
            indexes = self._treeView.selectionModel().selectedIndexes()
            model = self._treeView.model()
            while len(indexes) > 0:
                index = indexes.pop(0)
                if isinstance(index, tuple):
                    index, depth = index
                else:
                    depth = 0
                if index.column() != 0:
                    continue

                if depth > 10:
                    # Avoid infinite loop with recursive links
                    break

                if model.hasChildren(index):
                    self._treeView.setExpanded(index, True)
                    for row in range(model.rowCount(index)):
                        childIndex = model.index(row, 0, index)
                        indexes.append((childIndex, depth + 1))

    def _collapseAllSelected(self):
        """Collapse all selected items of the tree.

        The depth is limited to avoid infinite loop with recursive links.
        """
        selection = self._treeView.selectionModel()
        indexes = selection.selectedIndexes()
        model = self._treeView.model()
        while len(indexes) > 0:
            index = indexes.pop(0)
            if isinstance(index, tuple):
                index, depth = index
            else:
                depth = 0
            if index.column() != 0:
                continue

            if depth > 10:
                # Avoid infinite loop with recursive links
                break

            if model.hasChildren(index):
                self._treeView.setExpanded(index, False)
                for row in range(model.rowCount(index)):
                    childIndex = model.index(row, 0, index)
                    indexes.append((childIndex, depth + 1))

    def close_files_silxview(self):
        "Close HDF5 sources selected in the silx viewer."
        with OverrideCursor():
            selection = self._treeView.selectionModel()
            indexes = selection.selectedIndexes()
            model = self._treeView.model()
            source_ids = set()

            for index in indexes:
                if index.column() != 0:
                    continue
                h5 = model.data(
                    index, role=silx.gui.hdf5.Hdf5TreeModel.H5PY_OBJECT_ROLE)
                if h5 is not None:
                    source_ids.add(h5.file.filename)

            for source_id in source_ids:
                self.close_source(source_id)

    # End Silx stuff

    def select_and_open_files(self):
        "Open HDF5/TIFF files"
        filters = []
        filters.append("Image files (*.h5 *.hdf *.hdf5 *.tif *.tiff)")
        filters.append("HDF5 files (*.h5 *.hdf *.hdf5)")
        filters.append("TIFF files (*.tif *.tiff)")
        filters.append("All files (*)")

        filenames = self.askFileName(
            title="Open file(s)", filter=";;".join(filters),
            settingname="OpenDir", multiple=True)
        if filenames is None:
            return
        with OverrideCursor():
            self.open_files(filenames)

    def open_files(self, filenames):
        "Open one or more files, with ExhaleWindow owning the source handles."
        last_source = None

        for filename in filenames:
            source = open_source(filename)
            source_id = source.source_id

            if source_id in self.fileSettings and self.fileSettings[source_id].is_open:
                print("Warning: opened already opened file", source_id)
                last_source = self.fileSettings[source_id]
                continue

            self.fileSettings[source_id] = source
            self.loadedFileComboBox.addItem(source.filename, source)

            if source.kind == "hdf5":
                self._treeModel.insertH5pyObject(source.handle, source.filename)
                if source.root is not None:
                    self._treeView.setSelectedH5Node(source.root)

            last_source = source

        if last_source is not None:
            ix = self.loadedFileComboBox.findData(last_source)
            if ix >= 0:
                self.loadedFileComboBox.setCurrentIndex(ix)
            self.loadedFileChanged()

    def close_all_files(self):
        for source_id in list(self.fileSettings):
            self.close_source(source_id)

    def close_source(self, source_id):
        source = self.fileSettings.get(source_id)
        if source is None or not source.is_open:
            return
        if source.kind == "hdf5":
            self._dataPanel.removeDatasetsFrom(source.handle)
            self._treeModel.removeH5pyObject(source.handle)
        source.close()

        ix = self.loadedFileComboBox.findData(source)
        if ix >= 0:
            self.loadedFileComboBox.removeItem(ix)
        self.refresh_element_display_names()


    def post_setup(self, project_file, files):
        "Called after setting up UI to start loading data etc"
        ExceptionDialog.install(self)
        if project_file is not None:
            self.load_project_file(project_file)
        if files is not None and files:
            self.open_files(files)

    def clear_project(self):
        # Close open files first
        self.close_all_files()

        # Clear model/state
        self.fileSettings.clear()
        self.elementSettings.clear()
        self.selectedElements.clear()
        self.imageSettings.clear()
        self.currentElement = None
        self.currentImage = None

        # Clear UI
        self.loadedFileComboBox.clear()
        self.loadedFileAlias.clear()

        self.elementList.clear()
        self.analysisElements.clear()
        self.imageList.clear()

        self.elementPlot.clear()
        self.elementHistogramPlot.clear()
        self.elementHistogramPlot.addHistogram(
            [0], [1, 100], color='gray', fill=True, baseline=0, copy=False)

        # Reset image-analysis / napari state if wanted
        if self.naparihelper is not None:
            self.naparihelper.set_sample(None)

        # Let any dependent widgets rebuild
        self.selectedElementsChanged.emit()

    def refresh_project_ui(self):
        # Loaded files dropdown
        self.loadedFileComboBox.clear()
        for source in self.fileSettings.values():
            if source.is_open:
                self.loadedFileComboBox.addItem(source.filename, source)
                if source.kind == "hdf5" and source.handle is not None:
                    self._treeModel.insertH5pyObject(source.handle, source.filename)

        # Rebuild image list
        self.imageList.clear()
        for num, im in sorted(self.imageSettings.items()):
            self.imageList.addImage(num, im)

        # Rebuild element list for current file
        self.loadedFileChanged()
        # Rebuild any dependent controls
        self.selectedElementsChanged.emit()

        # Show something sensible
        if self.imageList.count() > 0:
            self.imageList.setCurrentRow(0)
        elif self.elementList.count() > 0:
            self.elementList.setCurrentRow(0)
        else:
            self.setImageControlsEnabled(False)
            self.setElementControlsEnabled(False)

    PROJECT_FILTERS = ";;".join(["EXHALE projects (*.xhp)", "All files (*)"])
    def load_project(self):
        "Load project settings"
        filename = self.askFileName(
            title="Load EXHALE project", filter=self.PROJECT_FILTERS,
            settingname="Project")
        if not filename:
            return
        return self.load_project_file(filename)

    def load_project_file(self, filename):
        self.clear_project()
        try:
            with OverrideCursor():
                projectio.load_project(self, filename)
        except Exception as e:
            self.errorMsg.showMessage(f"Loading failed:\n{e}")
        self.refresh_project_ui()

    def save_project(self):
        "Load project settings"
        filename = self.askFileName(
            title="Save EXHALE project", filter=self.PROJECT_FILTERS,
            settingname="Project", save=True)
        if not filename:
            return
        try:
            with OverrideCursor():
                projectio.save_project(self, filename)
        except Exception as e:
            self.errorMsg.showMessage(f"Saving failed:\n{e}")
            return


    def askFileName(self, title, filter=None, settingname=None,
                    save=False, multiple=False,
                    settingdefault=None,
                    directory=None, defaultfilename=None):
        "Show a file dialog and select one or more files"
        setting = self.settings.value(settingname, settingdefault
                                      ) if settingname is not None else None
        if directory is None:
            directory = setting if type(setting) is str else None
        dialog = qt.QFileDialog(parent=self, caption=title,
                                directory=directory, filter=filter)
        if defaultfilename is not None:
            dialog.selectFile(defaultfilename)
        dialog.setOption(qt.QFileDialog.DontUseNativeDialog, True)
        if save:
            dialog.setAcceptMode(qt.QFileDialog.AcceptSave)
            def fix_ext(filt):
                exts = re.findall(r"\.[a-z]*", filt)
                f = dialog.selectedFiles()[0]
                if f and exts:
                    fb, fe = os.path.splitext(f)
                    if fe not in exts:
                        dialog.selectFile(fb + exts[0])
            dialog.filterSelected.connect(fix_ext)
        elif multiple:
            dialog.setFileMode(qt.QFileDialog.ExistingFiles)
        else:
            dialog.setFileMode(qt.QFileDialog.ExistingFile)
        dialog.exec()
        files = dialog.selectedFiles()
        if not dialog.result() or not files:
            return None
        if save:
            exts = re.findall(r"\.[a-z]*", dialog.selectedNameFilter())
            for i, f in enumerate(files):
                fb, fe = os.path.splitext(f)
                if fe not in exts:
                    files[i] = fb + exts[0]
        if settingname is not None:
            self.settings.setValue(settingname, os.path.dirname(files[0]))
        return files if multiple else files[0]


