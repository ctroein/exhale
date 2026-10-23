#!/usr/bin/env python3
"""Main Exhale window and integration of project, image, and analysis workflows."""

import os

# import importlib
import re

# from typing import Optional
# from collections.abc import Iterable
from qtpy import QtCore, QtGui, QtWidgets

from . import appearance, application_description, application_name, application_title, icons
from .analysis.controller import AnalysisController
from .analysis.correlation_controller import CorrelationController
from .data.projectdata import ProjectData
from .exceptiondialog import ExceptionDetailsDialog, ExceptionDialog
from .imaging.element_controller import ElementController
from .imaging.image_controller import ImageController
from .imaging.listwidgets import ElementListWidget, ImageListWidget
from .main_window_ui import Ui_MainWindow
from .project.project_tab import ProjectTab
from .project.projectmanager import ProjectManager
from .project.projectstatemanager import ProjectStateManager
from .project.sourcemanager import SourceManager
from .runtimeinfo import runtime_environment_html
from .settings_dialog import SettingsDialog
from .tooltips import (
    CORRELATION_TABS,
    MAIN_WINDOW,
    MAIN_WINDOW_TABS,
    apply_tab_tooltips,
    apply_tooltips,
)
from .widgets import IconToolButton, initialize_splitter_on_show

ACTIVE_TAB_SETTINGS_KEY = "window/active_tab"
WINDOW_GEOMETRY_SETTINGS_KEY = "window/geometry"
SPLITTER_SETTINGS_PREFIX = "window/splitters"


def scale_font(widget: QtWidgets.QWidget, scale: float):
    "Rescale font of widget and its children"
    font = widget.font()
    font.setPointSizeF(font.pointSizeF() * scale)
    widget.setFont(font)


class MainWindow(QtWidgets.QMainWindow, Ui_MainWindow):
    """Own the application shell and coordinate feature-specific controllers."""

    channelsChanged = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QtCore.QSettings("CIPA", application_name)
        self.appearance = appearance.initialize(self.settings)
        self.project_dir = None
        self.project_manager = ProjectManager(self)
        self.source_manager = SourceManager(self)
        # QApplication.instance().installEventFilter(self) # needed why?
        self.setupUi(self)
        self.setWindowTitle(application_title)
        self._configure_tooltips()

        self._exception_dialog = ExceptionDetailsDialog(self)

        self.reload_icons()
        self.appearance.changed.connect(self.reload_appearance)

        self.actionOpenFile.triggered.connect(self.source_manager.select_and_open_files)
        self.actionNewProject.triggered.connect(self.project_manager.new_project)
        self.actionOpenProject.triggered.connect(self.project_manager.open_project)
        self.actionSaveProject.triggered.connect(self.project_manager.save_project)
        self.actionSettings.triggered.connect(self.show_settings)
        self.actionAbout.triggered.connect(self.showAbout)
        self.actionQuit.triggered.connect(self.close)
        self._skip_next_quit_confirmation = False
        QtWidgets.QShortcut(
            QtGui.QKeySequence("Ctrl+Shift+Q"), self, activated=self.quit_without_confirmation
        )

        self.project_data = ProjectData()

        self.project_tab = ProjectTab(self)
        self.element_controller = ElementController(self)
        self.image_controller = ImageController(self)
        self.analysis_controller = AnalysisController(self)
        self.correlation_controller = CorrelationController(self)

        self.element_controller.setup()
        self.image_controller.setup()
        self.element_controller.refresh_sample_selector()
        self.analysis_controller.setup()
        self.correlation_controller.setup()
        self._configure_splitter_persistence()
        self.tabWidget.setCurrentIndex(0)
        self.project_state_manager = ProjectStateManager(self)
        self.project_state_manager.connect_sources()
        self.project_state_manager.dirtyChanged.connect(lambda _dirty: self.update_window_title())
        self.project_state_manager.mark_saved()
        self.update_window_title()
        geometry = self.settings.value(WINDOW_GEOMETRY_SETTINGS_KEY)
        if isinstance(geometry, QtCore.QByteArray):
            self.restoreGeometry(geometry)

    def update_window_title(self):
        project_name = self.project_dir.name if self.project_dir is not None else "Untitled"
        self.setWindowTitle(f"{application_title} — {project_name}[*]")
        dirty = getattr(self, "project_state_manager", None)
        self.setWindowModified(dirty is not None and dirty.is_dirty)

    def _configure_tooltips(self) -> None:
        """Describe controls whose scope or consequences are not obvious."""
        apply_tab_tooltips(self, self.tabWidget, MAIN_WINDOW_TABS)
        apply_tab_tooltips(self, self.correlationModes, CORRELATION_TABS)
        apply_tooltips(self, MAIN_WINDOW)

    def closeEvent(self, ev):
        skip_confirmation = self._skip_next_quit_confirmation
        self._skip_next_quit_confirmation = False
        if not self.project_state_manager.prepare_to_exit(skip_confirmation=skip_confirmation):
            ev.ignore()
            return
        self.image_controller.shutdown()
        self.analysis_controller.shutdown()
        self._save_splitter_states()
        current_tab = self.tabWidget.currentWidget()
        if current_tab is not None:
            self.settings.setValue(ACTIVE_TAB_SETTINGS_KEY, current_tab.objectName())
        self.settings.setValue(WINDOW_GEOMETRY_SETTINGS_KEY, self.saveGeometry())
        self.settings.sync()
        ev.accept()

    def _configure_splitter_persistence(self):
        """Restore every main-window splitter after its tab has usable geometry."""
        specifications = {
            "project_data": (self.project_tab.splitter, self.projectDataTab, (2, 2, 1)),
            "splitter": (self.splitter, self.dataTab, (1, 1, 2)),
            "analysis": (self.analysisSplitter, self.analysisTab, (180, 400, 200)),
            "analysis_left": (self.analysisLeftSplitter, self.analysisTab, (2, 1)),
            "analysis_right": (self.analysisRightSplitter, self.analysisTab, (2, 1)),
            "element_correlations": (
                self.elementCorrelationSplitter,
                self.elementCorrelationTab,
                (1, 3),
            ),
            "element_scatter": (
                self.elementScatterSplitter,
                self.elementScatterTab,
                (1, 3),
            ),
            "sample_similarities": (
                self.sampleSimilaritySplitter,
                self.sampleSimilarityTab,
                (1, 3),
            ),
            "cluster_distances": (
                self.clusterDistanceSplitter,
                self.clusterDistanceTab,
                (1, 3),
            ),
        }
        self._splitter_initializers = {
            name: initialize_splitter_on_show(
                splitter,
                visible_widget,
                proportions,
                self.settings.value(f"{SPLITTER_SETTINGS_PREFIX}/{name}"),
            )
            for name, (splitter, visible_widget, proportions) in specifications.items()
        }

    def _save_splitter_states(self):
        """Save splitters which have been initialized with visible geometry."""
        for name, initializer in self._splitter_initializers.items():
            if initializer.initialized:
                self.settings.setValue(
                    f"{SPLITTER_SETTINGS_PREFIX}/{name}", initializer.splitter.saveState()
                )

    def _restore_active_tab(self):
        """Restore global workspace state without affecting the project state."""
        object_name = self.settings.value(ACTIVE_TAB_SETTINGS_KEY)
        if not isinstance(object_name, str):
            return
        for index in range(self.tabWidget.count()):
            if self.tabWidget.widget(index).objectName() == object_name:
                self.tabWidget.setCurrentIndex(index)
                return

    def quit_without_confirmation(self):
        """Close immediately without showing the exit question."""
        self._skip_next_quit_confirmation = True
        self.close()

    def reload_icons(self):
        """Reload palette-dependent icons throughout the main window."""
        self.actionOpenFile.setIcon(icons.icon(icons.IconName.OPEN))
        self.actionOpenProject.setIcon(icons.icon(icons.IconName.PROJECT))
        self.actionSaveProject.setIcon(icons.icon(icons.IconName.SAVE))
        self.actionSettings.setIcon(icons.icon(icons.IconName.SETTINGS))
        self.actionAbout.setIcon(icons.icon(icons.IconName.INFO))
        self.actionQuit.setIcon(icons.icon(icons.IconName.QUIT))
        self.addProjectFilesButton.setIcon(icons.icon(icons.IconName.FILE_DATA))
        self.addSampleFilesButton.setIcon(icons.icon(icons.IconName.FILE))
        self.removeButton.setIcon(icons.icon(icons.IconName.DELETE))
        self.refreshChannelsButton.setIcon(icons.icon(icons.IconName.REFRESH))
        self.addImageButton.set_icon_name(icons.IconName.ADD_IMAGE)
        self.deleteImageButton.set_icon_name(icons.IconName.DELETE)
        self.showSingleElementButton.set_icon_name(icons.IconName.ELEMENT)
        self.composeSave.setIcon(icons.icon(icons.IconName.IMAGE))
        self.copyElementCorrelationTable.setIcon(icons.icon(icons.IconName.COPY))
        self.copySampleSimilarityTable.setIcon(icons.icon(icons.IconName.COPY))
        self.copyClusterDistanceTable.setIcon(icons.icon(icons.IconName.COPY))
        self.saveElementCorrelationPlot.setIcon(icons.icon(icons.IconName.SCREENSHOT))
        self.saveClusterDistancePlot.setIcon(icons.icon(icons.IconName.SCREENSHOT))
        self.saveElementScatterPlot.setIcon(icons.icon(icons.IconName.SCREENSHOT))
        self.saveSampleSimilarityPlot.setIcon(icons.icon(icons.IconName.SCREENSHOT))
        self.analysisScreenshot.set_icon_name(icons.IconName.SCREENSHOT)
        self.analysisFit.set_icon_name(icons.IconName.MAXIMIZE)
        for button in self.findChildren(IconToolButton):
            button.reload_icon()

    def reload_appearance(self):
        """Refresh components that cache palette-derived resources."""
        icons.initialize()
        self.reload_icons()
        self.elementPlot.reload_appearance()
        self.elementHistogramPlot.reload_appearance()
        self.elementList.reload_icons()
        self.analysisElements.reload_icons()
        self.imageList.reload_icons()
        self.project_tab.reload_icons()
        self.analysisLayerList.reload_appearance()
        self.correlation_controller.reload_appearance()
        if self.analysis_controller.naparihelper is not None:
            self.analysis_controller.naparihelper.set_theme(
                "dark" if appearance.is_dark() else "light"
            )

    def show_settings(self):
        SettingsDialog(self.settings, self).exec()

    def show_error(self, summary, details=None, title="Error"):
        summary = str(summary)
        if details is None:
            details = summary
        else:
            details = str(details)
            if (
                details != summary
                and not details.startswith(summary + "\n")
                and not details.rstrip().endswith(summary)
            ):
                details = f"{summary}\n\n{details}"
        self._exception_dialog.show_exception(title=title, summary=summary, details=details)

    def show_source_unavailable(self, source_id):
        """Show an expected data-file access failure without an internal-error dialog."""
        source = self.project_data.sources[source_id]
        message = f"The data file cannot be opened:\n{source.filename}"
        if source.open_error:
            message += f"\n\nCause: {source.open_error}"
        QtWidgets.QMessageBox.warning(self, "Data file unavailable", message)

    def show_tiff_read_error(self, filenames, error):
        """Report an expected TIFF input or decoder failure without an internal-error trace."""
        if isinstance(filenames, (str, os.PathLike)):
            filenames = [filenames]
        paths = "\n".join(map(str, filenames))
        if "requires the 'imagecodecs' package" in str(error):
            message = (
                "The TIFF compression requires the optional Python package imagecodecs. "
                "Install imagecodecs in Exhale's Python environment and try again."
            )
        else:
            message = f"Exhale could not read the element maps in the TIFF file.\n\n{error}"
        QtWidgets.QMessageBox.warning(
            self,
            "Cannot read TIFF file",
            f"{message}\n\nFile:\n{paths}",
        )

    def showAbout(self):
        """Show application credits and the detected runtime environment."""
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(f"About {application_name}")
        layout = QtWidgets.QVBoxLayout(dialog)

        heading = QtWidgets.QHBoxLayout()
        logo_height = round(self.fontMetrics().height() * 4)
        pixmap = icons.icon_pixmap(icons.IconName.APPLICATION, logo_height)
        logo = QtWidgets.QLabel(dialog)
        logo.setPixmap(pixmap)
        logo.setFixedSize(pixmap.size())
        heading.addWidget(logo, 0, QtCore.Qt.AlignVCenter)
        title = QtWidgets.QLabel(
            f'<span style="font-size: xx-large; font-weight: bold">{application_title}</span>',
            dialog,
        )
        title.setTextFormat(QtCore.Qt.RichText)
        heading.addWidget(title, 0, QtCore.Qt.AlignVCenter)
        layout.addLayout(heading)

        information = QtWidgets.QLabel(
            f"""
<p>{application_name} ({application_description}) was created for the<br>
{application_name} project at Lund University and MAX IV,
<a href="https://www.vr.se/english/swecris.html?project=2023-02821_Vinnova#/">
funded by Vinnova</a>.</p>
<p>© 2023–2026 Carl Troein, Tom Delaire, Bryan Falcones &amp; Emanuel Larsson.<br>
Licensed under the MIT License.</p>
<b>Runtime environment</b>{runtime_environment_html()}
""",
            dialog,
        )
        information.setTextFormat(QtCore.Qt.RichText)
        information.setOpenExternalLinks(True)
        information.setWordWrap(False)
        layout.addWidget(information)

        attribution = QtWidgets.QLabel(
            'Icons derived from <a href="https://tabler.io/icons">Tabler Icons</a> '
            "by Paweł Kuna, available under the MIT licence.",
            dialog,
        )
        attribution.setTextFormat(QtCore.Qt.RichText)
        attribution.setOpenExternalLinks(True)
        layout.addWidget(attribution)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok, parent=dialog)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        layout.setSizeConstraint(QtWidgets.QLayout.SetFixedSize)
        dialog.exec()

    def post_setup(self, project_dir, files):
        "Called after setting up UI to start loading data etc"
        ExceptionDialog.install(self)
        if project_dir is not None:
            self.project_manager.load_project_dir(project_dir)
        else:
            self.project_state_manager.recover_unsaved_project()
        if files is not None and files:
            self.source_manager.open_files(files)
        self._restore_active_tab()

    def clear_project(self):
        # Close open files first
        self.source_manager.close_source_handles()

        # Clear model/state
        self.project_data.clear()

        # Clear UI
        self.loadedFileComboBox.clear()

        self.elementHistogramPlot.clear_histogram()

        self.image_controller.clear_project()
        self.element_controller.clear_project()
        self.analysis_controller.clear_project()
        self.correlation_controller.clear_project()

        # Let any dependent widgets rebuild
        self.channelsChanged.emit()

    def refresh_project_ui(self):
        self.element_controller.refresh_sample_selector()
        # Rebuild any dependent controls
        self.channelsChanged.emit()

        # Show something sensible
        available_image_row = next(
            (
                row
                for row in range(self.imageList.count())
                if all(
                    element.data_source.is_available
                    for element in self.project_data.images[
                        self.imageList.item(row).data(ImageListWidget.IMG_NUM_ROLE)
                    ].elements.values()
                )
            ),
            None,
        )
        available_element_row = next(
            (
                row
                for row in range(self.elementList.count())
                if (ref := self.elementList.item(row).data(ElementListWidget.ELEMENT_REF_ROLE))
                is not None
                and ref.source_id in self.project_data.assets
                and self.project_data.assets[ref.source_id].is_available
            ),
            None,
        )
        if available_image_row is not None:
            self.imageList.setCurrentRow(available_image_row)
        elif available_element_row is not None:
            self.elementList.setCurrentRow(available_element_row)
        else:
            self.image_controller.set_controls_enabled(False)
            self.element_controller.set_controls_enabled(False)

    def askFileName(
        self,
        title,
        filter=None,
        settingname=None,
        save=False,
        multiple=False,
        settingdefault=None,
        directory=None,
        defaultfilename=None,
    ):
        "Show a file dialog and select one or more files"
        setting = (
            self.settings.value(settingname, settingdefault) if settingname is not None else None
        )
        if directory is None:
            directory = setting if type(setting) is str else None
        dialog = QtWidgets.QFileDialog(
            parent=self, caption=title, directory=directory, filter=filter
        )
        if defaultfilename is not None:
            dialog.selectFile(defaultfilename)
        dialog.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
        if save:
            dialog.setAcceptMode(QtWidgets.QFileDialog.AcceptSave)

            def fix_ext(filt):
                exts = re.findall(r"\.[a-z]*", filt)
                f = dialog.selectedFiles()[0]
                if f and exts:
                    fb, fe = os.path.splitext(f)
                    if fe not in exts:
                        dialog.selectFile(fb + exts[0])

            dialog.filterSelected.connect(fix_ext)
        elif multiple:
            dialog.setFileMode(QtWidgets.QFileDialog.ExistingFiles)
        else:
            dialog.setFileMode(QtWidgets.QFileDialog.ExistingFile)
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
