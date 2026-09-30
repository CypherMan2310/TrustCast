"""Write forecast products for one init from a pipeline result.

    data/products/<region>/<variable>/<YYYYmmdd>.nc          gridded layers for the map/API
    data/products/<region>/<variable>/<YYYYmmdd>.json        district summaries + explanations
    data/products/<region>/<variable>/latest.json            pointer to the newest init

Explanations use SHAP (TreeExplainer) of the gate model that produced that init's weights; when the
gate is disabled the reasons come from the skill tracker only, and the payload says so.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from trustcast import DISCLAIMER
from trustcast.blend.explain import explanation_sentence, top_features
from trustcast.pipeline import PipelineResult
from trustcast.verify.assemble import Bundle
from trustcast.verify.scoreboard import THRESHOLDS

UNITS = {"precip": "mm/day", "tmax": "degC"}


def _f(x) -> float | None:
    return None if x is None or not np.isfinite(x) else round(float(x), 3)


def product_dataset(res: PipelineResult, b: Bundle, init: pd.Timestamp) -> xr.Dataset:
    """Gridded layers of one init."""
    sel = {"init_time": np.datetime64(init)}
    ds = xr.Dataset({"final": res.final_det.sel(sel)})
    if res.lo is not None:
        ds["lo90"], ds["hi90"] = res.lo.sel(sel), res.hi.sel(sel)
    for t, p in res.probs.items():
        ds[f"prob_ge_{t}"] = p.sel(sel)
    land = np.isfinite(b.truth).any("time")
    raw = xr.concat(
        [f.det.sel(sel).where(land) for f in b.forecasts],
        dim=pd.Index([f.name for f in b.forecasts], name="source"),
    )
    ds["source_value"] = raw
    ds["disagreement"] = raw.std("source", skipna=True)
    ds["consensus"] = raw.mean("source", skipna=True)
    ds["weights"] = res.weights.sel(sel)
    ds["dmse"] = xr.concat(
        [res.dmse[n].sel(sel) for n in res.names], dim=pd.Index(res.names, name="source")
    )
    ds["defer"] = res.defer.sel(sel).astype("int8")
    ds["regime"] = res.regimes.sel(sel)
    ds = ds.drop_vars([v for v in ("init_time",) if v in ds.coords])
    ds.attrs.update(
        disclaimer=DISCLAIMER,
        variable=b.variable,
        region=b.region,
        units=UNITS[b.variable],
        init_time=str(init),
        generated_at=dt.datetime.now(dt.UTC).isoformat(),
    )
    return ds


def _gate_shap(
    res: PipelineResult, init: pd.Timestamp, cells: list[int], li: int
) -> list[tuple[str, float]]:
    """Top gate features (mean |SHAP|) for the rows of this init, lead and cells."""
    gp = res.gate
    if gp is None or not gp.models:
        return []
    q0 = max((q for q in gp.models if q <= init), default=None)
    if q0 is None:
        return []
    import shap

    _, nl, ny, nx = gp.grid.shape
    it = int(np.flatnonzero(res.final_det.init_time.values == np.datetime64(init))[0])
    case = gp.cidx
    ci = case // (nl * ny * nx)
    cl = (case // (ny * nx)) % nl
    cc = case % (ny * nx)
    rows = np.flatnonzero((ci == it) & (cl == li) & np.isin(cc, cells))
    if rows.size == 0:
        return []
    X = gp.X.iloc[rows]
    sv = shap.TreeExplainer(gp.models[q0]).shap_values(X)
    return [(n, round(v, 4)) for n, v in top_features(np.asarray(sv), list(X.columns), k=3)]


def district_summaries(
    res: PipelineResult, b: Bundle, init: pd.Timestamp, table: pd.DataFrame, gate_on: bool
) -> list[dict]:
    """Per-district, per-lead summary with explanation payload."""
    sel = {"init_time": np.datetime64(init)}
    lat, lon = b.like.lat.values, b.like.lon.values
    cell_index = {
        (round(float(a), 4), round(float(o), 4)): i * lon.size + j
        for i, a in enumerate(lat)
        for j, o in enumerate(lon)
    }
    thr = THRESHOLDS[b.variable]
    out = []
    for did, g in table.groupby("district_id"):
        w = g.weight.to_numpy()
        idx = [cell_index[(round(a, 4), round(o, 4))] for a, o in zip(g.lat, g.lon, strict=True)]

        def dmean(da: xr.DataArray, li: int, idx=idx, w=w) -> float | None:
            v = da.sel(sel).isel(lead_h=li).values.ravel()[idx]
            ok = np.isfinite(v)
            return _f((v[ok] * w[ok]).sum() / w[ok].sum()) if ok.any() else None

        leads = []
        for li in range(b.like.sizes["lead_h"]):
            vd = pd.Timestamp(res.final_det.sel(sel)["valid_day"].values[li]).date()
            wts = {}
            for s in res.names:
                wv = res.weights.sel(source=s, **sel).isel(lead_h=li).values.ravel()[idx]
                ok = np.isfinite(wv)
                wts[s] = round(float((wv[ok] * w[ok]).sum() / w[ok].sum()), 4) if ok.any() else 0.0
            val = dmean(res.final_det, li)
            probs = {str(t): dmean(p, li) for t, p in res.probs.items()}
            dfr = res.defer.sel(sel).isel(lead_h=li).values.ravel()[idx].astype(float)
            defer = bool((dfr * w).sum() / w.sum() >= 0.5)
            regime = str(res.regimes.sel(sel).isel(lead_h=li).values)
            top = _gate_shap(res, init, idx, li) if gate_on else []
            if not gate_on:
                top = [("recent skill of each model (decayed error)", 1.0)]
            ph = probs.get(str(thr[0])) if b.variable == "precip" else None
            sentence = (
                explanation_sentence(
                    g.district.iloc[0],
                    b.variable,
                    li + 1,
                    val if val is not None else np.nan,
                    wts,
                    regime,
                    top,
                    defer,
                    ph,
                )
                if val is not None
                else DISCLAIMER
            )
            leads.append(
                {
                    "lead_day": li + 1,
                    "valid_day": str(vd),
                    "value": val,
                    "lo90": dmean(res.lo, li) if res.lo is not None else None,
                    "hi90": dmean(res.hi, li) if res.hi is not None else None,
                    "probabilities": probs,
                    "weights": wts,
                    "top_features": top,
                    "regime": regime,
                    "defer": defer,
                    "sentence": sentence,
                }
            )
        out.append(
            {
                "district_id": did,
                "district": g.district.iloc[0],
                "state": g.state.iloc[0],
                "coverage": float(g.coverage.iloc[0]) if "coverage" in g else 1.0,
                "leads": leads,
            }
        )
    return out


def write_products(
    res: PipelineResult,
    b: Bundle,
    inits: list[pd.Timestamp],
    table: pd.DataFrame,
    root: Path,
    gate_on: bool,
    meta: dict,
    subdir: str = "products",
) -> list[Path]:
    """Write grid + district products for ``inits``; update latest.json for live products."""
    folder = root / subdir / b.region / b.variable
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for init in inits:
        stem = f"{init:%Y%m%d}"
        ds = product_dataset(res, b, init)
        ds.to_netcdf(folder / f"{stem}.nc")
        payload = {
            "disclaimer": DISCLAIMER,
            "region": b.region,
            "variable": b.variable,
            "units": UNITS[b.variable],
            "init_time": str(init),
            "meta": meta,
            "districts": district_summaries(res, b, init, table, gate_on),
        }
        (folder / f"{stem}.json").write_text(json.dumps(payload, default=str), encoding="utf-8")
        written.append(folder / f"{stem}.nc")
    if subdir == "products" and inits:
        latest = max(inits)
        (folder / "latest.json").write_text(
            json.dumps({"init_time": str(latest), "stem": f"{latest:%Y%m%d}"}), encoding="utf-8"
        )
    return written
