import setuptools
import os.path
from setuptools.command.install import install

executables = {'run_exhale': 'EXHALE'}

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="exhale",
    version="1.1.1",
    author="Carl Troein, Tom Delaire, Emanuel Larsson, Bryan Falcones, Karina Thånell et al.",
    author_email="carl.troein@cec.lu.se",
    description="EXHALE, Efficient X-ray Hub Aiding Lung Explorations",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/ctroein/exhale",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.6',
    install_requires=['numpy', 'scipy', 'matplotlib', 'scikit-learn',
                      'pandas', 'h5py', 'napari', 'magicgui'],
    package_data={ '': ['*.ui', '*.ico', '*.svg', '*.json', '*.h5'] },
    entry_points={'console_scripts':
        ['run_exhale = run_exhale:main'],
    },

)
