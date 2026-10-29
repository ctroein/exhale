"""Central catalogue and application helpers for static interface tooltips."""

from qtpy import QtCore, QtWidgets

MAIN_WINDOW_TABS = {
    "projectDataTab": "Organize samples, source files and element selection.",
    "dataTab": "Adjust element-map presentation and compose 3-channel images.",
    "analysisTab": "Segmentation and clustering of cells and elements.",
    "correlationsTab": (
        "Explore correlations, intensity relationships and distances between segmented clusters."
    ),
}

CORRELATION_TABS = {
    "elementCorrelationTab": "Pairwise correlations between element maps in a sample.",
    "elementScatterTab": "Compare intensities between two elements in a sample.",
    "sampleSimilarityTab": (
        "Compare samples using their within-sample element-correlation patterns."
    ),
    "clusterDistanceTab": (
        "Compare mean nearest-centroid distances between segmented element clusters."
    ),
}

MAIN_WINDOW = {
    "dataRootLabel": "Common source-data directory used to shorten displayed file paths.",
    "resolutionValue": "Physical size represented by one image pixel; used when drawing scale bars.",
    "resolutionUnits": "Physical size represented by one image pixel; used when drawing scale bars.",
    "addProjectFilesButton": "Import HDF5 files as separate samples or TIFF files as one sample.",
    "addSampleFilesButton": "Add source files to the selected sample.",
    "removeButton": (
        "Remove the selected sample or file from the project. Files on disk are not deleted."
    ),
    "mapsLabel": (
        "Choose whether each element follows the project setting, is included in this sample, "
        "or is excluded from it."
    ),
    "channelsLabel": (
        "Set which elements samples use by default. Sample-specific choices take precedence."
    ),
    "refreshChannelsButton": "Sort selected elements first",
    "loadedFileComboBox": "Select the sample whose element maps and composed images are shown.",
    "label": (
        "Choose whether each element follows the project setting, is included in this sample, "
        "or is excluded from it."
    ),
    "composeLayoutCB": "Choose how the selected element maps are arranged in the composed image.",
    "composeColors": "Choose a color scheme for the composed image.",
    "addImageButton": "Create a blank composed image for the selected sample.",
    "deleteImageButton": "Delete the selected composed image.",
    "imageSettingsScopeCombo": (
        "Choose whether edits affect this element throughout the sample or only in the current "
        "image."
    ),
    "elementName": "Display name for the element in the selected settings scope.",
    "showSingleElementButton": "Toggle between the adjusted element map and the composed image.",
    "elementNormalizer": "Transformation applied before displaying or composing the element map.",
    "gammaValue": "Exponent applied after scaling values to the display range.",
    "elementNormalizeMin": (
        "Values at or below this limit are mapped to the bottom of the display range."
    ),
    "elementNormalizeMax": (
        "Values at or above this limit are mapped to the top of the display range."
    ),
    "elementPercButton": "Set the display limits to the 5th and 95th percentiles.",
    "elementSDButton": "Set the display limits to the mean plus or minus three standard deviations.",
    "analysisSampleComboBox": "Select the sample to analyze or whose saved result is displayed.",
    "analysisChNuclei": "Element map used to detect nuclei (usually P).",
    "analysisChTissue": "Element map used to identify tissue.",
    "label_8": "Select the element maps to partition and measure in detected regions.",
    "analysisRun": "Run segmentation and clustering for this sample.",
    "analysisOptions": "Configure nucleus filtering, expansion, and element-intensity clustering.",
    "analysisExport": "Export channels, masks, cluster labels, and tables from this result.",
    "analysisSaveView": "Save current view",
    "analysisFit": "Fit image to view",
    "showElementCorrelationValues": "Show correlation coefficients inside matrix cells.",
    "elementCorrelationPalette": "Choose the color scale used for correlation values.",
    "copyElementCorrelationTable": "Copy the correlation matrix as tab-separated text.",
    "saveElementCorrelationPlot": "Save the current plot as a PNG or SVG image.",
    "elementScatterBins": (
        "Number of bins along each axis; the two-dimensional grid contains this number squared "
        "of cells. Higher values refine the smoothed density estimate."
    ),
    "saveElementScatterPlot": "Save the current plot as a PNG or SVG image.",
    "sampleSimilaritySamples": (
        "Select at least two samples. Only active elements common to every selection are compared."
    ),
    "sampleSimilarityExcluded": (
        "Elements omitted because they are unavailable or inactive in one or more selected "
        "samples. The second column shows their availability."
    ),
    "showSampleSimilarityValues": "Show correlation coefficients inside matrix cells.",
    "sampleSimilarityPalette": "Choose the color scale used for correlation values.",
    "copySampleSimilarityTable": "Copy the correlation matrix as tab-separated text.",
    "saveSampleSimilarityPlot": "Save the current plot as a PNG or SVG image.",
    "showClusterDistanceValues": "Show distances, normalized distances or null-model percentiles inside matrix cells.",
    "clusterDistanceSecondary": "Show the spread of observed nearest-cluster distances.",
    "clusterDistanceValue": (
        "Show distances in project units or pixels, null-model normalized distances, "
        "or null-model percentiles among random placements "
        "within the union of segmented cluster masks."
    ),
    "clusterDistancePalette": "Choose the sequential color scale used for distances.",
    "copyClusterDistanceTable": "Copy the directed distance matrix as tab-separated text.",
    "saveClusterDistancePlot": "Save the current matrix as PDF, PNG or SVG.",
}

IMAGE_SETTINGS_DIALOG = {
    "composeScalebarColor": "Choose the scale-bar color.",
    "composeScalebarBgColor": "Choose the scale-bar background color.",
    "composePanelLabelColor": "Choose the panel-label color.",
    "composeElementLabelsColored": "Color each element label using that element's image color.",
    "composeDPI": "Raster resolution used when exporting the composed image to PDF.",
    "applyProjectDefaults": "Replace this image's presentation settings with the project defaults.",
    "useAsProjectDefaults": (
        "Use this image's presentation settings as defaults for new images in this project."
    ),
}

ANALYSIS_SETTINGS_DIALOG = {
    "clusterMinK": "Range of intensity-class counts considered for each element map.",
    "clusterMaxK": "Range of intensity-class counts considered for each element map.",
    "nucleiExpansion": "Distance in pixels used to expand detected nuclei into surrounding regions.",
    "nucleiMinArea": "Discard detected nuclei smaller than this many pixels.",
}

SETTINGS_DIALOG = {
    "saveProjectOnExitCheckBox": (
        "Save changes to an existing project when Exhale closes, without asking first."
    ),
    "autosaveProjectCheckBox": (
        "Write a separate recovery file while editing. The saved project is not replaced."
    ),
}

SCATTER_FIT = "Fit the data to the plot area"

IMAGE_CANVAS_FIT = "Fit the full image (Home)"
IMAGE_ELEMENT_ADJUST = "Edit this element's presentation while keeping the composed image visible."
IMAGE_BORDER_COLOR = "Choose the border color for the composed image."
IMAGE_SHOW_COMPOSED = "Show the composed image and hide the element histogram and settings."
IMAGE_ELEMENT_COLOR = "Choose color for this element in the composed image."
LAYER_DRAG = "Drag to reorder"
LAYER_VISIBLE = "Show layer"
LAYER_OPACITY = "Opacity"
LAYER_ADDITIVE = "Add this layer's RGB values to the layers below it."
LAYER_GAIN = "Increase the display brightness of the raw nuclei or tissue layer."
LAYER_CATEGORICAL = "Cycle categorical palette"
LAYER_COLOR = "Choose color"


def apply_tooltips(root: QtCore.QObject, catalogue: dict[str, str]) -> None:
    """Apply static tooltips by object name and reject stale catalogue entries."""
    for object_name, text in catalogue.items():
        target = root.findChild(QtCore.QObject, object_name)
        if target is None:
            raise AttributeError(f"Tooltip target {object_name!r} was not found")
        target.setToolTip(text)


def apply_tab_tooltips(
    root: QtCore.QObject,
    tabs: QtWidgets.QTabWidget,
    catalogue: dict[str, str],
) -> None:
    """Apply tab-bar tooltips to pages found by object name."""
    for object_name, text in catalogue.items():
        page = root.findChild(QtWidgets.QWidget, object_name)
        if page is None or tabs.indexOf(page) < 0:
            raise AttributeError(f"Tooltip tab {object_name!r} was not found")
        tabs.setTabToolTip(tabs.indexOf(page), text)
