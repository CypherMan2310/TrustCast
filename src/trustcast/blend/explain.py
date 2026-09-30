"""L7 defer flag and explanations.

Defer flag ("low confidence, needs forecaster review"): the gate's predicted error of the blend
(weights x predicted source errors) is above the 90th percentile *and* the inter-source spread is
above the 75th percentile, both percentiles taken from the previous quarter's cases (leak-free).

Explanation payload per district: weight breakdown by source, top gate features by mean |SHAP|,
regime label, and a plain-language sentence from a deterministic template (no free text generation).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from trustcast import DISCLAIMER

SOURCE_LABELS = {
    "ecmwf_ifs": "ECMWF IFS (HRES)",
    "ecmwf_ifs_ctrl": "ECMWF IFS control",
    "ecmwf_aifs": "ECMWF AIFS (AI)",
    "ncep_gfs": "NOAA GFS",
    "dwd_icon": "DWD ICON",
    "cmc_gem": "ECCC GEM",
    "ncep_gefs": "NOAA GEFS ensemble",
    "ecmwf_ifs_ens": "ECMWF IFS ensemble",
    "ecmwf_aifs_ens": "ECMWF AIFS ensemble (AI)",
}
FEATURE_LABELS = {
    "rel_dmse": "recent skill relative to other models",
    "dmse": "recent error of the model",
    "abs_dev": "distance from the multi-model consensus",
    "dev": "departure from the consensus",
    "spread": "disagreement between models",
    "consensus": "consensus amount",
    "fc": "the model's own value",
    "lead_day": "lead time",
    "doy_sin": "season",
    "doy_cos": "season",
    "elevation_m": "terrain height",
    "slope_m_per_km": "terrain slope",
    "dist_coast_km": "distance from the coast",
    "regime": "weather regime",
    "member_std": "ensemble spread",
    "src_max": "wettest model",
    "src_min": "driest model",
    "n_src": "number of models available",
    "source": "model identity",
    "lat": "latitude",
    "lon": "longitude",
}


def defer_flags(
    pred_blend_err: np.ndarray,
    spread: np.ndarray,
    row_init: np.ndarray,
    q_err: float = 0.9,
    q_spread: float = 0.75,
) -> np.ndarray:
    """Boolean defer flag per case using thresholds from the previous quarter (NaN-safe)."""
    inits = pd.DatetimeIndex(row_init)
    quarters = inits.to_period("Q")
    flag = np.zeros(pred_blend_err.shape, bool)
    for q in quarters.unique():
        prev = quarters == (q - 1)
        cur = quarters == q
        e, s = pred_blend_err[prev], spread[prev]
        ok = np.isfinite(e) & np.isfinite(s)
        if ok.sum() < 1000:
            continue
        te, ts = np.quantile(e[ok], q_err), np.quantile(s[ok], q_spread)
        flag[cur] = (pred_blend_err[cur] > te) & (spread[cur] > ts)
    return flag


def top_features(
    shap_values: np.ndarray, columns: list[str], k: int = 3
) -> list[tuple[str, float]]:
    """Top-k features by mean |SHAP| (regime/season sin-cos merged by label)."""
    imp = np.abs(shap_values).mean(axis=0)
    agg: dict[str, float] = {}
    for c, v in zip(columns, imp, strict=True):
        agg[FEATURE_LABELS.get(c, c)] = agg.get(FEATURE_LABELS.get(c, c), 0.0) + float(v)
    return sorted(agg.items(), key=lambda kv: -kv[1])[:k]


def explanation_sentence(
    district: str,
    variable: str,
    lead_day: int,
    value: float,
    weights: dict[str, float],
    regime: str,
    top: list[tuple[str, float]],
    defer: bool,
    p_heavy: float | None = None,
) -> str:
    """Deterministic plain-language sentence; every number comes from the arguments."""
    ranked = sorted(weights.items(), key=lambda kv: -kv[1])
    lead_src, lead_w = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    unit = "mm" if variable == "precip" else "°C"
    what = "rainfall" if variable == "precip" else "maximum temperature"
    parts = [
        f"{district}, day {lead_day}: blended {what} {value:.1f} {unit}.",
        f"The blend leans most on {SOURCE_LABELS.get(lead_src, lead_src)} ({lead_w * 100:.0f} %)"
        + (
            f", then {SOURCE_LABELS.get(second[0], second[0])} ({second[1] * 100:.0f} %)"
            if second
            else ""
        )
        + ".",
    ]
    if top:
        parts.append("Main reasons: " + ", ".join(name for name, _ in top) + ".")
    parts.append(f"Regime: {regime.replace('_', ' ')}.")
    if p_heavy is not None and np.isfinite(p_heavy):
        parts.append(f"Chance of heavy rain (>= 64.5 mm): {p_heavy * 100:.0f} %.")
    if defer:
        parts.append(
            "Low confidence: models disagree and expected error is high; forecaster review advised."
        )
    parts.append(DISCLAIMER)
    return " ".join(parts)
