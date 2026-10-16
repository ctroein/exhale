"""Controller for composed-image editing, display, and export."""

from __future__ import annotations

from functools import partial

from qtpy import QtCore, QtGui, QtWidgets

from ..data.constants import CONCENTRATION_UNITS
from ..data.imagesettings import Colorschemes, ImageSettings, Layouts, Scalebars
from .image_settings_dialog import ImageSettingsDialog
from .imagecomposer import ImageComposer
from .listwidgets import ElementListWidget, ImageElementBox, ImageHeaderBox, ImageListWidget


class ImageController:
    """Own the Element maps tab's composed-image state and behavior."""

    def __init__(self, window):
        self.window = window
        self.current_image = None
        self.composer = ImageComposer()

        dialog = ImageSettingsDialog(window)
        self.settings_dialog = dialog
        self.scalebar_color = dialog.composeScalebarColor
        self.scalebar_background_enabled = dialog.composeScalebarBg
        self.scalebar_background_color = dialog.composeScalebarBgColor
        self.scalebar = dialog.composeScalebar
        self.font_size = dialog.composeFontsize
        self.dpi = dialog.composeDPI
        self.panel_labels = dialog.composePanelLabels
        self.element_labels = dialog.composeElementLabels
        self.element_borders = dialog.composeElementBorders
        self.colored_element_labels = dialog.composeElementLabelsColored
        self.panel_label_color = dialog.composePanelLabelColor
        self.apply_project_defaults_button = dialog.applyProjectDefaults
        self.use_as_project_defaults_button = dialog.useAsProjectDefaults

        window.composeSettings.clicked.connect(dialog.show)
        window.composeSettings.clicked.connect(dialog.raise_)
        dialog.buttonBox.clicked.connect(dialog.hide)
        self.apply_project_defaults_button.clicked.connect(self.apply_project_defaults)
        self.use_as_project_defaults_button.clicked.connect(self.use_as_project_defaults)

    def setup(self) -> None:
        """Build image controls and connect their behavior."""
        window = self.window
        window.imageSettingsScopeCombo.currentIndexChanged.connect(self._set_image_element_scope)
        window.imageChannelNameLabel.hide()
        window.imageSettingsScopeCombo.hide()
        window.showSingleElementButton.hide()
        window.showSingleElementButton.toggled.connect(self._toggle_single_element)

        window.imageElementButtonGroup = QtWidgets.QButtonGroup(window)
        header = ImageHeaderBox()
        window.imageElementBox.addLayout(header)
        window.imageElementButtonGroup.addButton(header.edit, -1)
        header.border.valueChanged.connect(self._border_width_changed)
        header.colorChanged.connect(self._border_color_changed)
        window.imageHeaderBox = header
        window.imageElementBoxes = []
        image_element_grid = QtWidgets.QGridLayout()
        window.imageElementBox.addLayout(image_element_grid)
        for slot in range(ImageSettings.MAX_ELEMENTS):
            box = ImageElementBox(Colorschemes(0).colors()[slot])
            window.imageElementBoxes.append(box)
            image_element_grid.addLayout(box, slot, 0)
            window.imageElementButtonGroup.addButton(box.edit, slot)
            box.combo.currentIndexChanged.connect(partial(self._element_changed, slot))
            box.colorChanged.connect(partial(self._color_changed, slot))
        window.imageElementBox.addWidget(header.edit)

        plot_pane = window.splitter.indexOf(window.verticalLayoutWidget)
        window.splitter.setCollapsible(plot_pane, False)
        window.verticalLayoutWidget.setMinimumWidth(window.elementSettingsPanel.sizeHint().width())

        self.set_controls_enabled(False)
        window.element_controller.set_controls_enabled(False)
        window.imageElementButtonGroup.buttonClicked.connect(self._edit_image_element)
        window.addImageButton.clicked.connect(self.create_image)
        window.deleteImageButton.clicked.connect(self._delete_image)
        window.imageList.itemChanged.connect(self._rename_image)
        window.imageList.currentItemChanged.connect(self._image_selected)

        window.composeLayoutCB.currentIndexChanged.connect(self._layout_changed)
        for layout in Layouts:
            window.composeLayoutCB.addItem(layout.description)
        window.composeColors.currentIndexChanged.connect(self._colors_changed)
        for colorscheme in Colorschemes:
            window.composeColors.addItem(colorscheme.description)
        for scalebar in Scalebars:
            self.scalebar.addItem(scalebar.description)
        for signal in (
            self.scalebar_color.colorChanged,
            self.scalebar_background_color.colorChanged,
            self.scalebar_background_enabled.toggled,
            self.scalebar.currentIndexChanged,
            self.font_size.valueChanged,
            self.dpi.valueChanged,
            self.panel_labels.toggled,
            self.element_labels.toggled,
            self.element_borders.toggled,
            self.colored_element_labels.toggled,
            self.panel_label_color.colorChanged,
        ):
            signal.connect(self._presentation_changed)

        window.elementPlot.pixelHovered.connect(self._mouse_over_plot)
        window.composeSave.clicked.connect(self.export_image)
        window.elementList.model().dataChanged.connect(self.sync_element_choices)
        window.channelsChanged.connect(self.sync_element_choices)
        self.initialize_empty_project()

    def shutdown(self) -> None:
        self.settings_dialog.close()

    @staticmethod
    def combo_index_for_data(combo, target):
        return next(
            (index for index in range(combo.count()) if combo.itemData(index) == target),
            -1,
        )

    def set_controls_enabled(self, enabled: bool) -> None:
        window = self.window
        for widget in (
            window.composeLayoutCB,
            window.composeColors,
            window.composeSave,
            window.composeSettings,
            self.scalebar,
            self.scalebar_color,
            self.scalebar_background_enabled,
            self.scalebar_background_color,
            self.element_borders,
            self.apply_project_defaults_button,
            self.use_as_project_defaults_button,
        ):
            widget.setEnabled(enabled)
        window.imageHeaderBox.setWidgetsEnabled(enabled)
        for box in window.imageElementBoxes:
            box.setWidgetsEnabled(enabled)
        self.update_show_buttons()

    def update_show_buttons(self) -> None:
        window = self.window
        active_slots = set() if self.current_image is None else set(self.current_image.elements)
        controls_enabled = window.composeLayoutCB.isEnabled()
        for slot, box in enumerate(window.imageElementBoxes):
            box.edit.setEnabled(controls_enabled and slot in active_slots)

    def store_settings(self, image: ImageSettings) -> None:
        window = self.window
        image.setColorscheme(Colorschemes(window.composeColors.currentIndex()))
        image.setLayout(Layouts(window.composeLayoutCB.currentIndex()))
        image.setScalebar(Scalebars(self.scalebar.currentIndex()))
        image.setScalebarColors(
            self.scalebar_color.color(),
            self.scalebar_background_color.color(),
            0.5 if self.scalebar_background_enabled.isChecked() else None,
        )
        image.setFontsize(self.font_size.value())
        image.setDPI(self.dpi.value())
        image.setLabels(self.panel_labels.isChecked(), self.element_labels.isChecked())
        image.setPanelLabelColor(self.panel_label_color.color())
        image.setElementBorders(self.element_borders.isChecked())
        image.setElementLabelsColored(self.colored_element_labels.isChecked())

    def apply_project_defaults(self) -> None:
        if self.current_image is None:
            return
        self.current_image.applyPresentationFrom(self.window.project_data.image_defaults)
        item = self.window.imageList.currentItem()
        if item is not None:
            self.show_image(item.data(ImageListWidget.IMG_NUM_ROLE))
            self.update_composed_image(reset_view=True)
        self.window.project_state_manager.project_changed()

    def use_as_project_defaults(self) -> None:
        if self.current_image is None:
            return
        self.window.project_data.image_defaults.applyPresentationFrom(self.current_image)
        self.window.project_state_manager.project_changed()

    def refresh_list(self, sample_id, selected_image_id=None) -> None:
        window = self.window
        if selected_image_id is None:
            item = window.imageList.currentItem()
            if item is not None:
                selected_image_id = item.data(ImageListWidget.IMG_NUM_ROLE)

        self.current_image = None
        with QtCore.QSignalBlocker(window.imageList):
            window.imageList.clear()
            for image_id, image in sorted(window.project_data.images.items()):
                if image.sample_id == sample_id and sample_id is not None:
                    window.imageList.addImage(image_id, image)
            row = next(
                (
                    row
                    for row in range(window.imageList.count())
                    if window.imageList.item(row).data(ImageListWidget.IMG_NUM_ROLE)
                    == selected_image_id
                ),
                0 if window.imageList.count() else -1,
            )
            window.imageList.setCurrentRow(row)

        if window.imageList.currentItem() is not None:
            image_id = window.imageList.currentItem().data(ImageListWidget.IMG_NUM_ROLE)
            self.show_image(image_id)
            self.update_composed_image(reset_view=True)
        else:
            self.set_controls_enabled(False)
            window.elementPlot.clear_image()

    def create_image(self, name=None) -> None:
        sample = self.window.element_controller.current_sample()
        if sample is None:
            return
        images = self.window.project_data.images
        image_id = max(images) + 1 if images else 1
        image = self.window.project_data.image_defaults.copyForSample(
            "New image" if name is None or isinstance(name, bool) else name,
            sample.sample_id,
            sample.asset_ids,
        )
        images[image_id] = image
        self.window.imageList.addImage(image_id, image)

    def sample_element_for_slot(self, image, slot):
        sample = self.window.project_data.samples[image.sample_id]
        key = image.channel_keys[slot]
        return self.window.element_controller.ensure_settings(sample.channels[key].ref)

    def update_composed_image(self, reset_view=False) -> None:
        image = self.current_image
        if image is None:
            return
        if (
            self.window.element_controller.current_element is not None
            and self.window.showSingleElementButton.isChecked()
        ):
            self.window.element_controller.display_current_element(reset_view=reset_view)
            return
        try:
            self.composer.display_composed_image(
                self.window.elementPlot, image, reset_view=reset_view
            )
        except (OSError, RuntimeError) as exc:
            self.window.elementPlot.clear_image()
            self.window.show_error("Cannot compose image", str(exc))

    def update_picker_colors(self) -> None:
        for slot, color in enumerate(self.current_image.colors()):
            box = self.window.imageElementBoxes[slot]
            with QtCore.QSignalBlocker(box):
                box.setColor(color)

    def show_image(self, image_id) -> None:
        window = self.window
        image = window.project_data.images[image_id]
        self.current_image = image
        window.element_controller.current_element = None
        self.clear_show_buttons()
        window.elementList.setCurrentRow(-1)
        self.set_controls_enabled(True)
        window.element_controller.set_controls_enabled(False)

        for control, value in (
            (window.composeLayoutCB, image.layout.value),
            (window.composeColors, image.colorscheme.value),
            (self.scalebar, image.scalebar.value),
        ):
            with QtCore.QSignalBlocker(control):
                control.setCurrentIndex(value)
        for control, value in (
            (self.scalebar_background_enabled, image.scalebarBgAlpha is not None),
            (self.panel_labels, image.panelLabels),
            (self.element_labels, image.elementLabels),
            (self.element_borders, image.elementBorders),
            (self.colored_element_labels, image.elementLabelsColored),
        ):
            with QtCore.QSignalBlocker(control):
                control.setChecked(value)
        for control, value in (
            (self.scalebar_color, image.scalebarColor),
            (self.scalebar_background_color, image.scalebarBgColor),
            (self.panel_label_color, image.panelLabelColor),
        ):
            with QtCore.QSignalBlocker(control):
                control.setColor(value)
        for control, value in ((self.font_size, image.fontsize), (self.dpi, image.dpi)):
            with QtCore.QSignalBlocker(control):
                control.setValue(value)
        with QtCore.QSignalBlocker(window.imageHeaderBox):
            window.imageHeaderBox.setColor(image.borderColor)
            window.imageHeaderBox.border.setValue(image.borderWidth)
        self.update_picker_colors()

        for slot, box in enumerate(window.imageElementBoxes):
            index = 0
            if slot in image.elements:
                ref = image.elements[slot].ref
                for candidate in range(1, box.combo.count()):
                    if box.combo.itemData(candidate) == ref:
                        index = candidate
                        break
            with QtCore.QSignalBlocker(box.combo):
                box.combo.setCurrentIndex(index)
        self.update_show_buttons()

    def clear_show_buttons(self) -> None:
        group = self.window.imageElementButtonGroup
        group.setExclusive(False)
        for button in group.buttons():
            button.setChecked(False)
        group.setExclusive(True)

    def select_element(self, slot=-1, *, reset_view=False) -> None:
        self.window.element_controller.select_image_element(slot, reset_view=reset_view)

    def _element_changed(self, slot, index) -> None:
        image = self.current_image
        if image is None:
            return
        box = self.window.imageElementBoxes[slot]
        if index == 0:
            image.setElement(slot, None)
        else:
            ref = box.combo.itemData(index)
            self.window.element_controller.ensure_settings(ref)
            sample, channel = self.window.project_data.channel_for_ref(ref)
            if sample.sample_id != image.sample_id:
                raise ValueError("Image element belongs to a different sample")
            image.setElement(slot, self.window.project_data.element_settings[ref], channel.key)
        self.update_show_buttons()
        self.select_element(-1, reset_view=True)

    def _set_image_element_scope(self, index) -> None:
        image = self.current_image
        slot = self.window.imageElementButtonGroup.checkedId()
        if image is None or slot < 0 or slot not in image.elements:
            return
        if index == 0 and slot in image.element_overrides:
            image.revertElementOverride(slot, self.sample_element_for_slot(image, slot))
        elif index == 1 and slot not in image.element_overrides:
            image.createElementOverride(slot)
        self.select_element(slot)

    def _toggle_single_element(self, checked) -> None:
        if self.current_image is None or self.window.element_controller.current_element is None:
            return
        if checked:
            self.window.element_controller.display_current_element(reset_view=True)
        else:
            self.update_composed_image(reset_view=True)

    def _color_changed(self, slot, color) -> None:
        if self.current_image is None:
            return
        self.current_image.setColor(slot, color)
        with QtCore.QSignalBlocker(self.window.composeColors):
            self.window.composeColors.setCurrentIndex(self.current_image.colorscheme.value)
        self.update_composed_image()

    def _border_width_changed(self, value) -> None:
        if self.current_image is not None:
            self.current_image.setBorderWidth(value)
            self.update_composed_image()

    def _border_color_changed(self, color) -> None:
        if self.current_image is not None:
            self.current_image.setBorderColor(color)
            self.update_composed_image()

    def _edit_image_element(self) -> None:
        if self.current_image is not None:
            self.select_element(self.window.imageElementButtonGroup.checkedId())

    def _delete_image(self) -> None:
        item = self.window.imageList.currentItem()
        if item is None:
            return
        image_id = item.data(ImageListWidget.IMG_NUM_ROLE)
        image = self.window.project_data.images[image_id]
        answer = QtWidgets.QMessageBox.question(
            self.window, "Delete image", f"Do you want to delete image '{image.name}'?"
        )
        if answer == QtWidgets.QMessageBox.StandardButton.Yes:
            self.window.elementPlot.clear_image()
            del self.window.project_data.images[image_id]
            self.current_image = None
            self.window.imageList.takeItem(self.window.imageList.row(item))

    def _rename_image(self, item) -> None:
        image_id = item.data(ImageListWidget.IMG_NUM_ROLE)
        if image_id in self.window.project_data.images:
            self.window.project_data.images[image_id].name = item.text()

    def _layout_changed(self) -> None:
        if self.current_image is not None:
            self.current_image.setLayout(Layouts(self.window.composeLayoutCB.currentIndex()))
            self.select_element(-1, reset_view=True)

    def _colors_changed(self) -> None:
        if self.current_image is not None:
            self.current_image.setColorscheme(
                Colorschemes(self.window.composeColors.currentIndex())
            )
            self.select_element(-1)
            self.update_picker_colors()

    def _presentation_changed(self) -> None:
        if self.current_image is not None:
            self.store_settings(self.current_image)
            self.select_element(-1)

    def _image_selected(self, current, _previous) -> None:
        if current is not None:
            self.show_image(current.data(ImageListWidget.IMG_NUM_ROLE))
            self.update_composed_image(reset_view=True)

    def _mouse_over_plot(self, canvas_pixel) -> None:
        image = self.current_image
        if image is None or canvas_pixel is None:
            QtWidgets.QToolTip.hideText()
            return
        coordinates = self.composer.map_coordinates(*canvas_pixel)
        if coordinates is None:
            QtWidgets.QToolTip.hideText()
            return
        x, y = coordinates
        info = f"Pos ({x}, {y}):\n" + "\n".join(
            f"{element.name}: {element.data[y, x]:.4g} {CONCENTRATION_UNITS}"
            for element in image.elements.values()
            if y < element.data.shape[0] and x < element.data.shape[1]
        )
        QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), info, self.window.elementPlot)

    def export_image(self) -> None:
        image = self.current_image
        if image is None:
            return
        filters = ImageComposer.get_format_filters()
        filename = self.window.askFileName(
            title="Save composed image",
            filter=";;".join(filters),
            settingname="ImageDir",
            save=True,
            defaultfilename=image.name + ".png",
            directory=(
                str(self.window.project_dir / "exports")
                if self.window.project_dir is not None
                else None
            ),
        )
        if filename is not None:
            self.composer.compose(image, filename)

    def sync_element_choices(self) -> None:
        window = self.window
        sample = window.element_controller.current_sample()
        available_refs = set()
        if sample is not None:
            available_refs = {
                channel.ref
                for channel in sample.effective_channels(
                    window.project_data.project_channels
                ).values()
                if channel.ref in window.project_data.element_settings
            }
        ordered_refs = [
            window.elementList.item(row).data(ElementListWidget.ELEMENT_REF_ROLE)
            for row in range(window.elementList.count())
            if window.elementList.item(row).data(ElementListWidget.ELEMENT_REF_ROLE)
            in available_refs
        ]
        for slot, box in enumerate(window.imageElementBoxes):
            combo = box.combo
            with QtCore.QSignalBlocker(combo):
                selected_ref = None
                if self.current_image is not None and slot in self.current_image.elements:
                    selected_ref = self.current_image.elements[slot].ref
                combo.clear()
                combo.addItem("(none)", userData=None)
                for ref in ordered_refs:
                    combo.addItem(window.project_data.element_settings[ref].name, userData=ref)
                selected_index = self.combo_index_for_data(combo, selected_ref)
                combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)

    def initialize_empty_project(self) -> None:
        self.current_image = None
        self.window.project_data.images.clear()
        self.window.imageList.clear()

    def rename_channel_key(self, asset_id, old_key, new_key) -> None:
        for image in self.window.project_data.images.values():
            for slot, element in image.elements.items():
                if element.ref.source_id == asset_id and image.channel_keys.get(slot) == old_key:
                    image.channel_keys[slot] = new_key
            for slot, (element, key, overridden) in list(image.suspended_elements.items()):
                if element.ref.source_id == asset_id and key == old_key:
                    image.suspended_elements[slot] = (element, new_key, overridden)

    def remove_asset_references(self, asset_id, refs) -> None:
        for image in self.window.project_data.images.values():
            for slot in [slot for slot, element in image.elements.items() if element.ref in refs]:
                image.setElement(slot, None)
            for slot, (element, _key, _overridden) in list(image.suspended_elements.items()):
                if element.ref in refs:
                    del image.suspended_elements[slot]
            image.sample_source_ids = tuple(
                value for value in image.sample_source_ids if value != asset_id
            )

    def remove_sample_images(self, sample_id) -> None:
        self.window.project_data.images = {
            image_id: image
            for image_id, image in self.window.project_data.images.items()
            if image.sample_id != sample_id
        }

    def clear_project(self) -> None:
        self.current_image = None
        self.window.imageList.clear()
        self.window.elementPlot.clear_image()
        self.set_controls_enabled(False)
