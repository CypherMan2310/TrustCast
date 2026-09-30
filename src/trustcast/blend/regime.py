"""L4 rule-based weather regimes (per init, lead; region level).

Regimes are computed from the *forecast consensus* (equal-weight mean of the raw sources), so they
are known at issue time, and from the IMD 1991-2020 climatology when available:

rain (JJAS)       monsoon_active  consensus region mean >= 1.5 x climatological mean
                  monsoon_break   consensus region mean <= 0.5 x climatological mean
                  monsoon_normal  otherwise
rain (other)      heavy_rain_risk any cell of the consensus >= 64.5 mm (cyclone / NE-monsoon events;
                                  no wind or pressure data are used, so this is a proxy)
                  dry             consensus region mean < 1 mm
                  wet_spell       otherwise
tmax              heat            consensus region mean Tmax >= 40 C, or >= climatology + 4.5 C
                  (else the season name)

MJO/RMM is not used (optional in the plan; not implemented).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

from trustcast.verify.data import season_of

RAIN_REGIMES = (
    "monsoon_active",
    "monsoon_break",
    "monsoon_normal",
    "heavy_rain_risk",
    "dry",
    "wet_spell",
)


def label_regimes(
    consensus: xr.DataArray, variable: str, clim_mean: xr.DataArray | None = None
) -> xr.DataArray:
    """Regime label per (init_time, lead_h) from the consensus forecast field."""
    dims = ("init_time", "lead_h")
    reg_mean = consensus.mean(("lat", "lon"), skipna=True).transpose(*dims).values
    reg_max = consensus.max(("lat", "lon"), skipna=True).transpose(*dims).values
    clim = None
    if clim_mean is not None:
        clim = clim_mean.mean(("lat", "lon"), skipna=True).transpose(*dims).values
    seasons = season_of(consensus["valid_day"].transpose(*dims).values)
    out = np.empty(reg_mean.shape, dtype=object)
    if variable == "precip":
        jjas = seasons == "monsoon_JJAS"
        c = clim if clim is not None else np.full(reg_mean.shape, np.nan)
        active = jjas & (reg_mean >= 1.5 * c)
        brk = jjas & (reg_mean <= 0.5 * c)
        out[jjas] = "monsoon_normal"
        out[active] = "monsoon_active"
        out[brk] = "monsoon_break"
        other = ~jjas
        out[other] = "wet_spell"
        out[other & (reg_mean < 1.0)] = "dry"
        out[other & (reg_max >= 64.5)] = "heavy_rain_risk"
    else:
        heat = reg_mean >= 40.0
        if clim is not None:
            heat |= reg_mean >= clim + 4.5
        out[:] = seasons
        out[heat] = "heat"
    out[~np.isfinite(reg_mean)] = "unknown"
    return xr.DataArray(
        out.astype(str),
        dims=dims,
        coords={"init_time": consensus.init_time, "lead_h": consensus.lead_h},
    )


def regime_counts(labels: xr.DataArray) -> pd.Series:
    """Number of (init, lead) cases per regime."""
    return pd.Series(labels.values.ravel()).value_counts()
