#!/usr/bin/env python3
"""Display and normalization settings for project and image channels."""

from dataclasses import dataclass, replace
from enum import Enum

import numpy as np
from scipy.stats import rankdata

from .channeldata import as_channel_data
from .source_refs import ElementRef


class Normalizers(Enum):
    "Available intensity normalizers"

    LINEAR = 0, "linear", "Linear"
    GAMMA = 1, "gamma", "Gamma"
    LOG = 2, "log", "Logarithmic"
    RANK = 3, "rank", "Rank"
    SQRT = 4, "sqrt", "Square root"
    ARCSINH = 5, "arcsinh", "Arcsinh"

    def __new__(cls, *args, **kwds):
        obj = object.__new__(cls)
        obj._value_ = args[0]
        return obj

    # ignore the first param since it's already set by __new__
    def __init__(self, _: str, cmname: str, description: str):
        self._cmname_ = cmname
        self._description_ = description

    # @property
    # def cmname(self):
    #     return self._cmname_

    @property
    def description(self):
        return self._description_


@dataclass
class ElementSettingsDefaults:
    """Starting values copied into newly materialized channel settings."""

    normalizer: Normalizers = Normalizers.LINEAR
    range_mode: str = "sd"
    standard_deviations: float = 3.0
    lower_percentile: float = 5.0
    upper_percentile: float = 95.0
    gamma: float = 1.0

    def __post_init__(self):
        if not isinstance(self.normalizer, Normalizers):
            raise TypeError("normalizer must be a Normalizers value")
        if self.range_mode not in ("minmax", "sd", "percent"):
            raise ValueError("range_mode must be minmax, sd, or percent")
        if self.standard_deviations <= 0:
            raise ValueError("standard_deviations must be positive")
        if not 0 <= self.lower_percentile < self.upper_percentile <= 100:
            raise ValueError("percentiles must be ordered between 0 and 100")
        if self.gamma <= 0:
            raise ValueError("gamma must be positive")

    def copy(self):
        return replace(self)

    def range_parameter(self):
        if self.range_mode == "sd":
            return self.standard_deviations
        if self.range_mode == "percent":
            return [self.lower_percentile, self.upper_percentile]
        return None

    def to_json(self):
        return {
            "normalizer": self.normalizer.name,
            "range_mode": self.range_mode,
            "standard_deviations": self.standard_deviations,
            "lower_percentile": self.lower_percentile,
            "upper_percentile": self.upper_percentile,
            "gamma": self.gamma,
        }

    @classmethod
    def from_json(cls, obj):
        return cls(
            normalizer=Normalizers[obj["normalizer"]],
            range_mode=obj["range_mode"],
            standard_deviations=float(obj["standard_deviations"]),
            lower_percentile=float(obj["lower_percentile"]),
            upper_percentile=float(obj["upper_percentile"]),
            gamma=float(obj["gamma"]),
        )


class ElementSettings:
    """Bind one channel map to its editable display settings.

    The data value is normalized to a ``ChannelData`` accessor. Copies retain
    the same backing data while owning independent presentation settings.
    """

    def __init__(self, ref: ElementRef, *, data, name=None, defaults=None):
        self.ref = ref
        self.name = name if name is not None else ref.item_id.rsplit("/", 1)[-1]
        self.data_source = as_channel_data(data)

        values = self.data
        self.dataRange = (values.min(), values.max())
        positives = values[values > 0]
        self.minPositive = positives.min() if positives.size else self.dataRange[1]
        self.trfRange = list(self.dataRange)
        defaults = ElementSettingsDefaults() if defaults is None else defaults.copy()
        self.normalizer = defaults.normalizer
        self.gamma = defaults.gamma
        self.color = None
        self.setMinmaxByMode(defaults.range_mode, defaults.range_parameter())

    @property
    def data(self):
        """Materialized channel data retained for existing consumers."""
        return self.data_source.array()

    def release_data_cache(self):
        """Discard file-backed materialized data when it can be reread."""
        self.data_source.release_cache()

    def copy(self):
        e = type(self).__new__(self.__class__)
        e.__dict__.update(self.__dict__)
        e.trfRange = self.trfRange.copy()
        return e

    def getNormalizer(self):
        return self.normalizer.cmname

    def setMinmax(self, mm, val):
        "Set current min OR max from percentage"
        if not mm:
            self.trfRange[mm] = self.minConstraint(val, None)[0]
        else:
            self.trfRange[mm] = self.maxConstraint(val, None)[0]

    def setMinmaxByMode(self, mode, param=None):
        modes = ["minmax", "sd", "percent"]
        if mode not in modes:
            raise ValueError(f"mode must be one of {modes}")
        if mode == "minmax":
            if self.normalizer == Normalizers.LOG:
                self.trfRange[0] = self.minPositive
            else:
                self.trfRange[0] = self.dataRange[0]
            self.trfRange[1] = self.dataRange[1]
            return

        if mode == "sd":
            p = 3 if param is None else param
        else:  # percent
            p = [5, 95] if param is None else param

        if self.normalizer == Normalizers.LOG:
            if mode == "sd":
                data = np.log10(self.data[self.data > 0])
                m, sd = data.mean(), data.std()
                mm = 10 ** (m + p * np.array([-sd, sd]))
            else:
                mm = np.percentile(self.data[self.data > 0], p)
            self.trfRange[0] = max(self.minPositive, mm[0])
            self.trfRange[1] = min(self.dataRange[1], mm[1])
        else:
            if mode == "sd":
                m, sd = self.data.mean(), self.data.std()
                mm = m + p * np.array([-sd, sd])
            else:
                mm = np.percentile(self.data, p)
            self.trfRange[0] = max(self.dataRange[0], mm[0])
            self.trfRange[1] = min(self.dataRange[1], mm[1])

    def transformedData(self):
        data = self.data
        vmin, vmax = self.trfRange

        if self.normalizer == Normalizers.ARCSINH:
            data = np.arcsinh((data - vmin) / (vmax - vmin))
            data[~np.isfinite(data)] = 0
            return data
        if self.normalizer == Normalizers.LOG:
            vmin = np.log10(vmin if vmin > 0 else self.minPositive)
            vmax = np.log10(vmax)
            with np.errstate(divide="ignore"):
                data = np.log10(data)
        elif self.normalizer == Normalizers.RANK:
            vmin = (data < vmin).sum() / (data.size - 1)
            vmax = (data < vmax).sum() / (data.size - 1)
            data = (rankdata(data) - 1).reshape(data.shape) / (data.size - 1)

        with np.errstate(divide="ignore", invalid="ignore"):
            data = np.maximum(0.0, np.minimum(1.0, (data - vmin) / (vmax - vmin)))
        if self.normalizer == Normalizers.GAMMA:
            data = data**self.gamma
        elif self.normalizer == Normalizers.SQRT:
            data = np.sqrt(data)

        data[~np.isfinite(data)] = 0
        # print("trf", data.min(), data.max(), self.normalizer.description, vmin, vmax)
        return data

    def minConstraint(self, x, y):
        lower_bound = 0 if self.normalizer == Normalizers.LOG else min(0, self.dataRange[0])
        return max(lower_bound, min(self.trfRange[1], x)), y

    def maxConstraint(self, x, y):
        return min(self.dataRange[1], max(self.trfRange[0], x)), y
