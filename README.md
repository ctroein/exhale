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

On Linux, desktop-menu registration is explicit and applies only to the current user:

```bash
exhale --install-desktop
```

Before uninstalling EXHALE, remove that registration with:

```bash
exhale --remove-desktop
uv tool uninstall exhale-lung
```

## Developer documentation

Architecture, the file-by-file code overview, and development conventions are
indexed in [`docs/README.md`](docs/README.md).
