# Exhale
## Efficient X-ray Hub Aiding Lung Explorations

This project aims to develop a specialized tool for investigating elemental aspects of chronic lung diseases. 

From the [VINNOVA project
description](https://www.vinnova.se/en/p/exhale--efficient-x-ray-hub-aiding-lung-explorations/):  
The purpose of this project is to advance understanding and treatment of
chronic lung diseases, leading causes of mortality worldwide, by
characterizing elements in lung tissue suspected to impact their
pathogenesis. The industrial partners TrulyLabs and AnaMar in collaboration
with MAX IV, Lung Biology and Correlative Image Processing and Analysis
(CIPA) fom Lund University, aim to streamline a workflow of X-ray imaging
studies for lung diseases, making these methods more accessible for
biomedical companies and clinical researchers.

## Currect functionality

* Loading HDF5 files with XRF data from the NanoMAX beamline at MAX IV.
* Composing element maps into publication-ready figures.
* Segmentation of cells and clustering of areas in element maps.

## Installation

EXHALE can be installed from PyPI in an isolated environment with
[uv](https://docs.astral.sh/uv/):

```bash
uv tool install --python 3.12 exhale-lung
```

Windows and macOS users who prefer a packaged application over uv or pip can
download it from the [GitHub releases page](https://github.com/ctroein/exhale/releases).
Developers can also install EXHALE from a Git checkout.

On Linux, run the following command to add EXHALE to the current user's desktop
environment and application menu:

```bash
exhale --install-desktop
```

To remove the desktop and menu entry, run:

```bash
exhale --remove-desktop
```

To uninstall an EXHALE installation managed by uv, run:

```bash
uv tool uninstall exhale-lung
```

## Developer documentation

Developer documentation is located in [`docs/`](docs/README.md).
