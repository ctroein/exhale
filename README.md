# Exhale
## Efficient X-ray Hub Aiding Lung Explorations

<p align="center">
  <img src="artwork/screenshots/segmentation_20261023.png"
       alt="EXHALE segmentation results"
       width="900">
</p>

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

### Linux

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if needed,
then choose the segmentation backends you want.

For StarDist (TensorFlow):

```bash
uv tool install --python 3.12 'exhale-xrf[stardist]'
```

For Cellpose, MONAI U-Net and SMP U-Net (PyTorch; Cellpose also needs DINOv3):

```bash
uv tool install --python 3.12 --with-requirements https://raw.githubusercontent.com/ctroein/exhale/main/requirements-cellpose.txt 'exhale-xrf[cellpose,monai,smp]'
```

For MONAI U-Net alone:

```bash
uv tool install --python 3.12 'exhale-xrf[monai]'
```

MONAI U-Net's 1.6 MB trained checkpoint downloads on first use.

For SMP U-Net with its trained ResNet18 encoder:

```bash
uv tool install --python 3.12 'exhale-xrf[smp]'
```

Its 50 MB trained checkpoint downloads on first use. No DINOv3 installation is needed.

To also include StarDist, use `'exhale-xrf[stardist,cellpose,monai,smp]'` with the same additional
requirements argument. Plain `exhale-xrf` installs viewing, composition and
analysis of existing results without neural segmentation backends. Unavailable
backends are disabled in the application.

Run `exhale` to start the application. To add it to the current user's desktop
environment and application menu:

```bash
exhale --install-desktop
```

To update the application and its selected backends:

```bash
uv tool upgrade exhale-xrf
```

On Linux, Settings also offers daily update checks and a Check now button.
Checks notify you of newer stable releases without installing anything. For a
writable uv tool installation owned by your account, Update now closes Exhale,
runs the upgrade, checks startup, and reopens it. Normal project saving applies
before closing. Other Exhale instances must be closed first. Update results and
the log location are shown after restarting. Automatic checks can be disabled
in Settings.

uv retains the installation settings, including extras and additional
requirements. To change backend selection, rerun `uv tool install` with the
wanted extras and, for Cellpose, the requirements argument.

To uninstall, remove the desktop/menu entry before removing the application:

```bash
exhale --remove-desktop
uv tool uninstall exhale-xrf
```

### Windows

Windows 10 or later with 64-bit compatibility is required. Download the
`exhale-…-setup.exe` installer from the
[GitHub releases page](https://github.com/ctroein/exhale/releases) and run it.

The installer offers StarDist, Cellpose, both, or neither before setup. It
downloads a private Python environment and the selected packages; internet
access is required, but an existing Python or uv installation is not.
Use the Start menu or optional desktop shortcut to launch EXHALE.

Settings offers daily update checks, Check now, and Update now. Application
updates preserve the selected backends and validate a new runtime before
switching to it. You can also download and run a newer installer; use that to
update the launcher/setup tools, change backends, or repair the installation.
Uninstall through Windows Settings; the private runtime and shortcuts are
removed while projects, trained models and application settings are retained.

### macOS

Download the Apple Silicon (`arm64`) or Intel (`x86_64`) DMG from the
[GitHub releases page](https://github.com/ctroein/exhale/releases), drag
EXHALE.app into Applications, and open it there. Setup downloads Python and the
selected segmentation backends; neither Python nor uv needs to be installed
beforehand. Intel Macs support StarDist but not the current Cellpose backend.
The launcher requires macOS 13 or newer; Cellpose's PyTorch requires at least
macOS 14 on Apple Silicon, and dependencies may require newer versions.

The Mac app is not Developer ID signed or notarized. macOS may block its first
launch; see [Apple's explanation and opening options](https://support.apple.com/102445).

Subsequent launches open the installed application. Hold Option while opening
EXHALE.app to change backends, repair the installation, or remove the private
runtime. Settings offers daily update checks and Update now, which preserves
the backends and validates a new runtime before switching to it. To update the
launcher/setup tools, quit EXHALE and replace the app with a newer release; setup
will install its bundled release with your previous backend choices. For removal, use
**Remove Runtime** in setup, then move EXHALE.app to Trash. Projects, model files,
and application settings are retained.

Alternatively, use the same uv installation, backend selection and update
commands as on Linux. Start the application with `exhale`. The desktop/menu
registration commands are Linux-only; to uninstall a Mac uv installation, run:

```bash
uv tool uninstall exhale-xrf
```

App-managed environments are separate from installations made with
`uv tool install`.

### pip and source installations

Use a virtual environment with a supported Python version (3.11–3.13).
**Windows StarDist requires Python 3.11** because of its TensorFlow dependency.

For StarDist:

```bash
python -m pip install 'exhale-xrf[stardist]'
```

For Cellpose, MONAI U-Net and SMP U-Net (Apple Silicon required on macOS):

```bash
python -m pip install 'exhale-xrf[cellpose,monai,smp]' -r https://raw.githubusercontent.com/ctroein/exhale/main/requirements-cellpose.txt
```

For SMP U-Net alone, use `python -m pip install 'exhale-xrf[smp]'`.
For MONAI U-Net alone, use `python -m pip install 'exhale-xrf[monai]'`; no
DINOv3 requirements file is needed. Use `'exhale-xrf[stardist,cellpose,monai,smp]'` with
the same requirements argument to include all four methods. For a Git checkout:

```bash
python -m pip install -e '.[stardist,cellpose,monai,smp]' -r requirements-cellpose.txt
./run_exhale.py
```

Omit unwanted extras and the requirements file when Cellpose is not needed.
On Windows, launch the checkout with `python run_exhale.py`.

### DINOv3 and trained models

The additional requirements file pins DINOv3 to a tested source archive; Git is
not required. For a particular EXHALE release, replace `main` in the requirements
URL with its `vVERSION` tag and append `==VERSION` to the package specification.
A version-pinned uv installation must be reinstalled with a newer version
specification to upgrade.

Trained weights for all four methods are downloaded on first use to the model directory in
application settings. The same mechanism is used for installed applications and
Git checkouts; the weights are not included in the application installer.
DINOv3 code and derived model weights retain the
[DINOv3 license](exhale/resources/licenses/DINOv3-LICENSE.md).

## Developer documentation

Developer documentation is located in [`docs/`](docs/README.md).
