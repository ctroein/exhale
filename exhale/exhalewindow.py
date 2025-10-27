#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Jan 30 22:33:00 2024

@author: carl
"""

import os
import sys
import traceback
# import collections
import multiprocessing
import signal
import numpy as np
# from typing import Optional
# from collections.abc import Iterable
from functools import partial
import importlib

import silx.io
from silx.gui import qt, icons, hdf5
from silx.gui.qt import Qt, QApplication
# from silx.gui.plot import PlotWidget
from silx.gui.plot.items.core import ItemChangedType
from silx.app.view.DataPanel import DataPanel

from .exceptiondialog import ExceptionDialog
from .element import ElementSettings, Normalizers
from .imagecompose import ImageSettings, Layouts, Colorschemes
from .copyfigure import add_clipboard_to_figures
from .appversion import exhale_version
from .listwidgets import ImageElementBox
from .listwidgets import ElementListWidget, ImageListWidget

import napari
# from napari.qt import QtViewer
from .cluster_analysis.xrf_interface import XrfViewer

# Rebuild UI code on the fly; useful while developing with Spyder+Kite
resdir = importlib.resources.files("exhale.resources")
ui_files = (resdir.joinpath("exhale_qt.ui"), resdir.joinpath("../exhale_qt.py"))
if os.path.getmtime(ui_files[0]) > os.path.getmtime(ui_files[1]):
    print("Recompiling UI")
    uic = importlib.import_module(qt.BINDING + ".uic")
    with open(ui_files[1], 'w') as f:
        uic.compileUi(ui_files[0], f)
    # Alternative: load UI straight from XML
    # Ui_ExhaleWindow = uic.loadUiType(resdir.joinpath("exhale_qt.ui"))[0]

from .exhale_qt import Ui_ExhaleWindow

class ExhaleWindow(qt.QMainWindow, Ui_ExhaleWindow):
    "Main window of this thing"
    selectedElementsChanged = qt.Signal() # The set of selected elements changed

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = qt.QSettings('CIPA', 'Exhale')
        QApplication.instance().installEventFilter(self)
        self.setupUi(self)
        self.setWindowTitle(f'Exhale {exhale_version}')

        self.errorMsg = qt.QErrorMessage(self)
        self.errorMsg.setSizeGripEnabled(True)
        self.errorMsg.setWindowModality(Qt.WindowModal)

        self.actionAbout.triggered.connect(
            lambda: qt.QMessageBox.information(
                self, "About",
                "This software is part of the EXHALE project at Lund "
                "University and MAX IV, <a href='https://www.vr.se/english/"
                "swecris.html?project=2023-02821_Vinnova#/'>"
                "funded by Vinnova</a>.<br>2023-2025."))

        self.__displayIt = None

        self._treeView = hdf5.Hdf5TreeView(self)
        self._treeModel = hdf5.Hdf5TreeModel(self._treeView, ownFiles=False)
        self._create_silx_view()
        self._treeView.activated.connect(self.displaySelectedData)

        """
        Main data classes.
            _loadedFiles lets us find h5 objects and list/close all open files
            elementSettings stores color settings for all elements we've viewed
            a path is (filename, path_in_file)
            selectedElements holds checkboxed elements, available for images
            currentElement is the currently selected in the Elements list
            currentImage is the selected image, exclusive with currentElement
            imageSettings holds settings for all images
        """
        self._loadedFiles = {} # name -> hdf5.File
        self.elementSettings = {} # path -> ElementSettings
        self.selectedElements = set() # paths of selected elements
        self.currentElement = None # ElementSettings
        self.imageSettings = {} # id -> ImageSettings
        self.currentImage = None # ImageSettings

        self.create_dataTab()
        self.create_analysisTab()

        # Groups to be searched/expanded after load
        self._h5GroupsToExpand = []

    def cleanup(self):
        "Some last-second cleanup so we can exit cleanly"
        if self.napviewer:
            self.napviewer.close()

    # All about the clustering tab

    def create_analysisTab(self):
        "Prepare data analysis tab with Napari viewer"
        self.napviewer = None
        def tab_check():
            if (self.tabWidget.currentWidget() == self.analysisTab and
                self.napviewer is None):
                self.initialize_analysisTab()
        self.tabWidget.currentChanged.connect(tab_check)

    def initialize_analysisTab(self):
        "Actually initialize the data analysis tab"

        viewer = napari.viewer.Viewer(show=False)
        viewer.theme = 'light'
        self.napviewer = viewer
        self.napwidget = napari.qt.QtViewer(viewer)

        self.xrf_viewer = XrfViewer(self, viewer)

        dock = qt.QVBoxLayout()
        dock.addWidget(qt.QLabel("XRF Analysis"))
        abut = qt.QPushButton("Analyze element maps")
        def abut_txt():
            analyzed = self.xrf_viewer.image_dict.keys()
            n = len(self.selectedElements.difference(analyzed))
            abut.setText(f"Analyze {n} element maps")
        dock.addWidget(abut, 0)
        self.selectedElementsChanged.connect(abut_txt)
        def analyze():
            analyzed = self.xrf_viewer.image_dict.keys()
            new = self.selectedElements.difference(analyzed)
            for path in new:
                self.xrf_viewer.run_analysis(
                    path, self.elementSettings[path].data)
        abut.clicked.connect(analyze)
        dock.addStretch()

        hb = qt.QHBoxLayout()
        hb.setContentsMargins(0, 0, 0, 0)
        hb.addLayout(dock, 0)
        hb.addWidget(self.napwidget, 1)
        self.analysisTab.setLayout(hb)

        # self.napworker = napari.qt.create_worker()
        # dat = np.random.rand(10, 10)
        # viewer.add_image(dat)



    # All about the data/elements/images tab

    def setImageControlsEnabled(self, enabled : bool):
        "Enable/disable inputs that are relevant to composing an image"
        self.composeLayout.setEnabled(enabled)
        self.composeColors.setEnabled(enabled)
        self.composeShow.setEnabled(enabled)
        for box in self.imageElementBoxes:
            box.setWidgetsEnabled(enabled)
        self.composeSave.setEnabled(enabled)
        self.composeSettings.setEnabled(enabled)

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
            # Update existing element image
            self.elementPlot.addImage(es.transformedData(), legend='e',
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
        self.elementPlot.addImage(es.transformedData(), legend='e',
                                  replace=True, copy=False)

    def editElement(self, elementpath):
        "Big UI update when an element is selected for editing"
        # The element should already have settings at this point
        es = self.elementSettings[elementpath]
        self.currentElement = es
        self.currentImage = None
        with qt.QSignalBlocker(self.imageList):
            self.imageList.setCurrentRow(-1)
        self.setImageControlsEnabled(False)
        self.showCurrentElement()

    def createImage(self, name):
        "Add the named composed image to the list of images (and display it?)"
        num = max(self.imageSettings.keys()) + 1 if self.imageSettings else 1
        im = ImageSettings(name)
        im.setColorscheme(Colorschemes(self.composeColors.currentIndex()))
        im.layout = Layouts(self.composeLayout.currentIndex())
        self.imageSettings[num] = im
        self.imageList.addImage(num, im)

    def updateComposedImage(self):
        "Recompute and replace/draw the merged image"
        if im := self.currentImage:
            assert self.currentElement is None
            m = im.mergedImage()
            if m is None:
                self.elementPlot.clear()
            else:
                self.elementPlot.addImage(
                    m, legend='m', origin=(0, 0), copy=False)

    def updatePickerColors(self):
        "Update the image element color pickers from the current image"
        colors = self.currentImage.colors()
        for i, box in enumerate(self.imageElementBoxes):
            with qt.QSignalBlocker(box):
                box.setColor(colors[i])

    def showComposedImage(self, imgnum):
        "Update what composed image is shown"
        im = self.imageSettings[imgnum]
        self.currentImage = im
        self.currentElement = None
        self.elementList.setCurrentRow(-1)
        self.setImageControlsEnabled(True)
        self.setElementControlsEnabled(False)

        with qt.QSignalBlocker(self.composeLayout):
            self.composeLayout.setCurrentIndex(im.layout.value)
        with qt.QSignalBlocker(self.composeColors):
            self.composeColors.setCurrentIndex(im.colorscheme.value)
        self.updatePickerColors()
        # for wh in range(2):
        #     with qt.QSignalBlocker(self.composeSize[wh]):
        #         self.composeSize[wh].setValue(im.pdfSize[wh])
        # Find the corrent index for each dropdown
        for i, box in enumerate(self.imageElementBoxes):
            ix = 0
            if i in im.elements:
                es = im.elements[i]
                # Search through the combo, but we could maintain the
                # order as in selectedElements or something
                for j in range(1, box.combo.count()):
                    if box.combo.itemData(j) == es.path:
                        ix = j
                        break
            with qt.QSignalBlocker(box.combo):
                box.combo.setCurrentIndex(ix)

    def create_dataTab(self):
        "Set up everything in the elements/images tab"

        def clear_and_open():
            "Select new file to load"
            self.close_all_files()
            self.select_and_open_files()
        self.loadFileButton.clicked.connect(clear_and_open)

        def ensure_exists(path):
            "Create element settings if needed"
            if path not in self.elementSettings:
                filename, fpath = path
                # TODO: add user-defined default for normalizer and params. Copy the most recent?
                es = ElementSettings(self._loadedFiles[filename][fpath])
                self.elementSettings[es.path] = es

        def select_element(item : qt.QListWidgetItem):
            "Element to be selected (has been checkboxed)"
            item.setCheckState(Qt.CheckState.Checked)
            # sel.addItem(el.takeItem(el.row(item)))
            path = item.data(ElementListWidget.H5_PATH_ROLE)
            ensure_exists(path)
            self.selectedElements.add(path)
            self.selectedElementsChanged.emit()
            sync_settings_and_compose()
        el = self.elementList
        el.itemActivated.connect(select_element)

        def deselect_element(item):
            "Element to be deselected (checkbox was unchecked)"
            # el.addItem(sel.takeItem(sel.row(item)))
            item.setCheckState(Qt.CheckState.Unchecked)
            path = item.data(ElementListWidget.H5_PATH_ROLE)
            self.selectedElements.discard(path)
            self.selectedElementsChanged.emit()
            sync_settings_and_compose()
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
                path = curr.data(ElementListWidget.H5_PATH_ROLE)
                ensure_exists(path)
                self.editElement(path)
        el.currentItemChanged.connect(curr_elem)

        def el_name_ch():
            "Current element name was changed"
            if not (es := self.currentElement):
                return
            name = self.elementName.text()
            es.name = name
            if self.currentImage is not None:
                # Currently adjusting settings for an element in image
                return
            for row in range(self.elementList.count()):
                it = self.elementList.item(row)
                if it.data(ElementListWidget.H5_PATH_ROLE) == es.path:
                    origname = es.path[1].rsplit('/', 1).pop()
                    it.setText(f"{name} ({origname})" if
                               name != origname else name)
                    break
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
                        self.composeShow.setChecked(True)

        def im_element_ch(elementnum, index):
            "An image-element dropdown selection changed"
            if im := self.currentImage:
                box = self.imageElementBoxes[elementnum]
                if index == 0: # Unset?
                    im.setElement(elementnum, None)
                else:
                    path = box.combo.itemData(index)
                    ensure_exists(path)
                    im.setElement(elementnum, self.elementSettings[path])
                im_element_show(-1) # Show image, not image-elements

        def im_color_ch(elementnum, color):
            "An image-element color changed"
            if im := self.currentImage:
                im.setColor(elementnum, color)
                with qt.QSignalBlocker(self.composeColors):
                    self.composeColors.setCurrentIndex(im.colorscheme.value)
                im_element_show(-1)

        self.imageElementBoxes = []
        self.imageElementButtonGroup = qt.QButtonGroup(self)
        self.imageElementButtonGroup.addButton(self.composeShow, -1)
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
                self.imageList.takeItem(self.imageList.row(it))
                del self.imageSettings[num]
                self.currentImage = None
                # Todo: if no current image, disable UI components
        self.deleteImageButton.clicked.connect(del_img)

        def layout_ch():
            "Image layout update"
            if im := self.currentImage:
                im.layout = Layouts(self.composeLayout.currentIndex())
                im_element_show(-1)
        self.composeLayout.currentIndexChanged.connect(layout_ch)
        for t in Layouts:
            self.composeLayout.addItem(t.description)

        def colors_ch():
            "Color scheme update"
            cs = Colorschemes(self.composeColors.currentIndex())
            if im := self.currentImage:
                im.setColorscheme(cs)
                im_element_show(-1)
                self.updatePickerColors()
        self.composeColors.currentIndexChanged.connect(colors_ch)
        for c in Colorschemes:
            self.composeColors.addItem(c.description)

        def sel_img(curr, prev):
            "Active image changed"
            if curr is not None:
                self.showComposedImage(
                    curr.data(ImageListWidget.IMG_NUM_ROLE))
                im_element_show(-1)
        self.imageList.currentItemChanged.connect(sel_img)

        # def tab_check():
        #     if self.tabWidget.currentWidget() == self.composeTab:
        #         self.updateComposeTab()
        # self.tabWidget.currentChanged.connect(tab_check)

        # def pdf_wh_ch(wh):
        #     if im := self.currentImage:
        #         im.setSize(wh, self.composeSize[wh].value())
        # self.composeSize = (self.composeWidth, self.composeHeight)
        # self.composeWidth.valueChanged.connect(pdf_wh_ch)

        def save_im():
            im = self.currentImage
            if not im:
                return
            filters = []
            filters.append("PNG (*.png)")
            filters.append("PDF (*.pdf)")
            filters.append("Postscript (*.ps *.eps)")
            filters.append("TIFF (*.tif *.tiff)")
            filters.append("SVG (*.svg)")
            filters.append("JPEG (*.jpg *.jpeg)")
            filters.append("All files (*)")
            filename = self.askFileName(
                title="Save composed image", filter=";;".join(filters),
                settingname="ImageDir", savesuffix="png",
                defaultfilename=im.name)
            if filename is not None:
                self.composePlot.saveGraph(filename, dpi=im.dpi())
        self.composeSave.clicked.connect(save_im)

        def sync_settings_and_compose():
            "Bring selectedElements, elementList, dropdowns in sync"
            for row in range(self.elementList.count()):
                it = self.elementList.item(row)
                if it.checkState() == Qt.CheckState.Checked:
                    path = it.data(ElementListWidget.H5_PATH_ROLE)
                    if path not in self.selectedElements:
                        print(f"Warn: missed {path} among selected")
                        ensure_exists(path)
                        self.selectedElements.add(path)

            for i, box in enumerate(self.imageElementBoxes):
                combo = box.combo
                curpaths = set()
                # Iterate from end but skip number 0 (no element)
                for row in range(combo.count() - 1, 0, -1):
                    path = combo.itemData(row)
                    if path not in self.selectedElements:
                        combo.removeItem(row)
                    else:
                        if (combo.itemText(row) !=
                            self.elementSettings[path].name):
                            combo.setItemText(
                                row, self.elementSettings[path].name)
                        curpaths.add(path)
                for path in self.selectedElements:
                    if path not in curpaths:
                        combo.addItem(self.elementSettings[path].name,
                                      userData=path)
        el.model().dataChanged.connect(sync_settings_and_compose)
        # el.model().rowsRemoved.connect(sync_settings_and_compose)

        # Set everything up before creating the initial image
        self.createImage("Untitled")


    ## Begin Silx viewer stuff

    def _create_silx_view(self):
        "Create widgets for the HDF5 exploration tab"
        # treeView = hdf5.Hdf5TreeView(self)
        treeView = self._treeView
        treeModel = self._treeModel

        toolbar = qt.QToolBar(self)
        toolbar.setIconSize(qt.QSize(16, 16))
        toolbar.setStyleSheet("QToolBar { border: 0px }")

        action = qt.QAction("Open", toolbar)
        action.setIcon(icons.getQIcon("document-open"))
        action.setToolTip("Open file(s)")
        action.triggered.connect(self.select_and_open_files)
        action.setShortcut(qt.QKeySequence(qt.Qt.CTRL | qt.Qt.Key_O))
        toolbar.addAction(action)
        self.menuFile.addSeparator()
        self.menuFile.addAction(action)

        action = qt.QAction("Close", toolbar)
        action.setIcon(icons.getQIcon("close"))
        action.setToolTip("Close current file")
        action.triggered.connect(self.close_file)
        action.setShortcut(qt.QKeySequence(qt.Qt.CTRL | qt.Qt.Key_W))
        toolbar.addAction(action)
        self.menuFile.addAction(action)

        toolbar.addSeparator()

        action = qt.QAction(toolbar)
        action.setIcon(icons.getQIcon("tree-expand-all"))
        action.setText("Expand all")
        action.setToolTip("Expand all selected items")
        action.triggered.connect(self._expandAllSelected)
        action.setShortcut(qt.QKeySequence(qt.Qt.CTRL | qt.Qt.Key_Plus))
        toolbar.addAction(action)
        treeView.addAction(action)
        # self.__expandAllAction = action

        action = qt.QAction(toolbar)
        action.setIcon(icons.getQIcon("tree-collapse-all"))
        action.setText("Collapse all")
        action.triggered.connect(self._collapseAllSelected)
        action.setShortcut(qt.QKeySequence(qt.Qt.CTRL | qt.Qt.Key_Minus))
        toolbar.addAction(action)
        treeView.addAction(action)
        # self.__collapseAllAction = action

        treeView.setSelectionMode(treeView.ExtendedSelection)

        treeModel.sigH5pyObjectLoaded.connect(self._h5FileLoaded)
        treeModel.sigH5pyObjectRemoved.connect(self._h5FileRemoved)
        # treeModel.sigH5pyObjectSynchronized.connect(self._h5FileSynchonized)
        treeModel.setDatasetDragEnabled(True)
        treeView.setModel(treeModel)
        treeView.setSizePolicy(qt.QSizePolicy.Preferred,
                               qt.QSizePolicy.Preferred)
        treeView.header().setStretchLastSection(True)
        treeView.header().resizeSections(qt.QHeaderView.ResizeToContents)
        # treeView.header().resizeSections(qt.QHeaderView.Interactive)

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

    def _getRelativePath(self, model, rootIndex, index):
        """Returns a relative path from an index to his rootIndex.

        If the path is empty the index is also the rootIndex.
        """
        path = ""
        while index.isValid():
            if index == rootIndex:
                return path
            name = model.data(index)
            if path == "":
                path = name
            else:
                path = name + "/" + path
            index = index.parent()

        # index is not a children of rootIndex
        raise ValueError("index is not a children of the rootIndex")

    def _getPathFromExpandedNodes(self, view, rootIndex):
        """Return relative path from the root index of the extended nodes"""
        model = view.model()
        rootPath = None
        paths = []
        indexes = [rootIndex]
        while len(indexes):
            index = indexes.pop(0)
            if not view.isExpanded(index):
                continue

            node = model.data(
                index, role=silx.gui.hdf5.Hdf5TreeModel.H5PY_ITEM_ROLE)
            path = node._getCanonicalName()
            if rootPath is None:
                rootPath = path
            path = path[len(rootPath):]
            paths.append(path)

            for child in range(model.rowCount(index)):
                childIndex = model.index(child, 0, index)
                indexes.append(childIndex)
        return paths

    def _indexFromPath(self, model, rootIndex, path):
        elements = path.split("/")
        if elements[0] == "":
            elements.pop(0)
        index = rootIndex
        while len(elements) != 0:
            element = elements.pop(0)
            found = False
            for child in range(model.rowCount(index)):
                childIndex = model.index(child, 0, index)
                name = model.data(childIndex)
                if element == name:
                    index = childIndex
                    found = True
                    break
            if not found:
                return None
        return index


    def _expandAllSelected(self):
        """Expand all selected items of the tree.

        The depth is fixed to avoid infinite loop with recurssive links.
        """
        QApplication.instance().setOverrideCursor(qt.Qt.WaitCursor)

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
        QApplication.instance().restoreOverrideCursor()

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

    def _findNamedGroup(self, group, names):
        for k, entity in group.items():
            if k in names:
                return entity
            if silx.io.utils.is_group(entity):
                g = self._findNamedGroup(entity, names)
                if g is not None:
                    return g
        return None


    def _h5FileLoaded(self, loadedH5):
        if loadedH5.file.filename == self.__displayIt:
            self.__displayIt = None
            self._dataPanel.setData(loadedH5)
        self._loadedFiles[loadedH5.file.filename] = loadedH5.file
        self.loadedFileLineEdit.setText(loadedH5.file.filename)

        added = False
        startgroup = self._findNamedGroup(loadedH5, ["plotselect"])
        if startgroup is not None:
            # Expand this group in the silx viewer
            self._h5GroupsToExpand.append(startgroup)
            # ...and assume it contains the elements
            for k, entity in startgroup.items():
                if silx.io.utils.is_dataset(entity):
                    self.elementList.addElement(k, entity)
                    added = True
        if not added:
            self.errorMsg.showMessage(
                "No elements found in input file " +
                os.path.basename(loadedH5.file.filename), "No elements")

    def _h5FileRemoved(self, removedH5):
        fname = removedH5.file.filename
        self._dataPanel.removeDatasetsFrom(removedH5)
        removedH5.close()
        if fname in self._loadedFiles:
            del self._loadedFiles[fname]

    # def _h5FileSynchonized(self, removedH5, loadedH5):
    #     self._dataPanel.replaceDatasetsFrom(removedH5, loadedH5)
    #     removedH5.close()

    def select_and_open_files(self):
        "Open files in the silx view"
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
        self.open_files(filenames)

    def open_files(self, filenames):
        "Open one or more files"
        for filename in filenames:
            if self.__displayIt is None:
                # Store the file to display it (loading could be async)
                self.__displayIt = filename
            self._treeView.findHdf5TreeModel().appendFile(filename)

        if len(self._h5GroupsToExpand) < 3:
            for startgroup in self._h5GroupsToExpand:
                self._treeView.setSelectedH5Node(startgroup)
            self._treeView.setFocus(qt.Qt.OtherFocusReason)
        self._h5GroupsToExpand = []

    def close_all_files(self):
        model = self._treeView.findHdf5TreeModel()
        for file in self._loadedFiles:
            if file is not None:
                model.removeH5pyObject(file)

    def close_file(self):
        """Close selected items in silx view"""
        QApplication.instance().setOverrideCursor(qt.Qt.WaitCursor)

        selection = self._treeView.selectionModel()
        indexes = selection.selectedIndexes()
        selectedItems = []
        model = self._treeView.model()
        h5files = set([])
        while len(indexes) > 0:
            index = indexes.pop(0)
            if index.column() != 0:
                continue
            h5 = model.data(
                index, role=silx.gui.hdf5.Hdf5TreeModel.H5PY_OBJECT_ROLE)
            rootIndex = index
            # Reach the root of the tree
            while rootIndex.parent().isValid():
                rootIndex = rootIndex.parent()
            rootRow = rootIndex.row()
            relativePath = self._getRelativePath(model, rootIndex, index)
            selectedItems.append((rootRow, relativePath))
            h5files.add(h5.file)

        model = self._treeView.findHdf5TreeModel()
        for h5 in h5files:
            model.removeH5pyObject(h5)

        QApplication.instance().restoreOverrideCursor()

    # End Silx stuff

    def post_setup(self, files, paramFile):
        "Called after setting up UI to start loading data etc"
        ExceptionDialog.install(self)
        if files is not None and files:
            self.open_files(files)
        if paramFile is not None:
            print(f"Should read settings from: {paramFile}")


    def askFileName(self, title, filter=None, settingname=None,
                    savesuffix=None, multiple=False,
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
#        if setting and type(setting) is not str:
#            dialog.restoreState(setting)
        dialog.setOption(qt.QFileDialog.DontUseNativeDialog, True)
        if savesuffix is not None:
            dialog.setAcceptMode(qt.QFileDialog.AcceptSave)
            dialog.setDefaultSuffix(savesuffix)
        elif multiple:
            dialog.setFileMode(qt.QFileDialog.ExistingFiles)
        else:
            dialog.setFileMode(qt.QFileDialog.ExistingFile)
        dialog.exec()
        files = dialog.selectedFiles()
        if not dialog.result() or not files:
            return None
        if settingname is not None:
            self.settings.setValue(settingname, os.path.dirname(files[0]))
        return files if multiple else files[0]


    @classmethod
    def run_application(windowclass, parser=None, parameters=[],
                        isChild=False):
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        res = 1
        try:
            progver = f'Exhale {exhale_version}'
            windowparams = {}
            if parser is not None:
                parser.add_argument('--version', action='version',
                                    version=progver)
                selmp = multiprocessing.get_start_method(
                    allow_none=True) is None
                if selmp:
                    parser.add_argument('--mpmethod', help='')
                args = parser.parse_args()
                windowparams = { k: args.__dict__[k] for k in parameters }
                if selmp and args.mpmethod:
                    multiprocessing.set_start_method(args.mpmethod)

            app = QApplication.instance()
            if not app:
                app = QApplication(sys.argv)
            add_clipboard_to_figures()
            app.setWindowIcon(qt.QIcon(str(resdir.joinpath("lungs.ico"))))
            window = windowclass()
            window.show()
            window.post_setup(**windowparams)
            if not isChild:
                app.lastWindowClosed.connect(app.quit);
                app.aboutToQuit.connect(window.cleanup)
                res = app.exec_()

        except Exception:
            traceback.print_exc()
            print('Press enter to quit')
            input()
        if not isChild :
            sys.exit(res)

