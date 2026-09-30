"""Per-cell running (decayed) bias removal for temperature (L1 option).

The pooled quantile map (bias.qm) corrects the distribution of a whole region but not biases that
differ from cell to cell (coast vs. mountains, model orography). This layer subtracts, per cell and
lead, the exponentially decayed mean error of already-verified windows (same leak-free rule as the
skill tracker). Cells without enough history are left unchanged. Used for Tmax only: an additive
correction is not appropriate for rain.
"""

from __future__ import annotations

import numpy as np
import xarray as xr

from trustcast.skill.tracker import decayed_bias


def decayed_bias_correction(
    fc: xr.DataArray, obs: xr.DataArray, half_life_days: float = 30.0, min_eff: float = 5.0
) -> xr.DataArray:
    """``fc`` minus its leak-free decayed per-cell bias (dims init_time, lead_h, lat, lon)."""
    bias = decayed_bias(fc, obs, half_life_days, "cell", min_eff)
    corrected = fc - bias.fillna(0.0)
    return corrected.where(np.isfinite(fc)).astype(np.float32)
