"""TRUSTCAST REST API (FastAPI). Run:  uvicorn trustcast.api.app:app --port 8000

Read-only over products written by ``scripts/run_forecast.py`` / ``scripts/build_replays.py`` and
reports written by the verification scripts; the only write is ``POST /v1/feedback/override``.
Every JSON response carries the disclaimer; CAP XML carries it in <restriction> and <description>.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
import yaml
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from trustcast import DISCLAIMER, __version__
from trustcast.alerts.bulletin import bulletin_numbers, render, validate
from trustcast.alerts.cap import alert_level, build_cap
from trustcast.api import schemas as S
from trustcast.blend.explain import SOURCE_LABELS
from trustcast.config import REPO_ROOT, data_root, load_config
from trustcast.skill.overrides import add_override, connect, load_overrides

app = FastAPI(
    title="TRUSTCAST API",
    version=__version__,
    description=f"Hybrid AI-NWP multi-model forecast blending (SIH26081). **{DISCLAIMER}**",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
_reports_dir = Path(os.environ.get("TRUSTCAST_REPORTS_DIR") or (REPO_ROOT / "reports"))
_reports_dir.mkdir(parents=True, exist_ok=True)
app.mount("/reports", StaticFiles(directory=_reports_dir), name="reports")  # figures, read-only
UNITS = {"precip": "mm/day", "tmax": "degC"}
EVENT_T = {"precip": "64.5", "tmax": "40.0"}


def root() -> Path:
    return Path(os.environ.get("TRUSTCAST_DATA_DIR") or data_root())


def reports() -> Path:
    return Path(os.environ.get("TRUSTCAST_REPORTS_DIR") or (REPO_ROOT / "reports"))


@lru_cache(maxsize=1)
def cfg():
    return load_config()


# ----------------------------------------------------------------------------- product access


def product_dir(region: str, variable: str) -> Path:
    if region not in cfg().regions:
        raise HTTPException(404, f"unknown region {region!r}")
    return root() / "products" / region / variable


def resolve_init(region: str, variable: str, init: str | None) -> str:
    folder = product_dir(region, variable)
    if init:
        stem = pd.Timestamp(init).strftime("%Y%m%d")
        if not (folder / f"{stem}.nc").exists():
            raise HTTPException(404, f"no product for {region}/{variable} init {init}")
        return stem
    latest = folder / "latest.json"
    if not latest.exists():
        raise HTTPException(
            503, f"no products yet for {region}/{variable}; run scripts/run_forecast.py"
        )
    return json.loads(latest.read_text())["stem"]


@lru_cache(maxsize=64)
def _open_nc(path: str, mtime: float) -> xr.Dataset:
    with xr.open_dataset(path) as ds:
        return ds.load()


def open_product(region: str, variable: str, stem: str) -> xr.Dataset:
    p = product_dir(region, variable) / f"{stem}.nc"
    return _open_nc(str(p), p.stat().st_mtime)


def open_districts(region: str, variable: str, stem: str) -> dict:
    p = product_dir(region, variable) / f"{stem}.json"
    if not p.exists():
        raise HTTPException(404, "district product missing")
    return json.loads(p.read_text(encoding="utf-8"))


def region_of(lat: float, lon: float) -> str:
    for name, r in cfg().regions.items():
        if (
            r.lat[0] - 0.125 <= lat <= r.lat[1] + 0.125
            and r.lon[0] - 0.125 <= lon <= r.lon[1] + 0.125
        ):
            return name
    raise HTTPException(404, "point outside the pilot regions")


def find_district(district_id: str, variable: str, init: str | None) -> tuple[str, str, dict, dict]:
    for region in cfg().regions:
        try:
            stem = resolve_init(region, variable, init)
        except HTTPException:
            continue
        payload = open_districts(region, variable, stem)
        for d in payload["districts"]:
            if d["district_id"] == district_id:
                return region, stem, payload, d
    raise HTTPException(404, f"district {district_id!r} not found in any product")


def _f(x) -> float | None:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(x) else round(x, 3)


def lead_index(ds: xr.Dataset, lead_day: int) -> int:
    if not 1 <= lead_day <= ds.sizes["lead_h"]:
        raise HTTPException(422, f"lead_day must be 1..{ds.sizes['lead_h']}")
    return lead_day - 1


def valid_day_of(ds: xr.Dataset, li: int, variable: str) -> dt.date:
    """Day the value refers to: IMD rain day (window end) or, for Tmax, the day of the maximum."""
    d = pd.Timestamp(ds["valid_day"].values[li])
    return (d - pd.Timedelta(days=1)).date() if variable == "tmax" else d.date()


# ----------------------------------------------------------------------------- endpoints


@app.get("/v1/health", response_model=S.Health)
def health():
    products, notes = {}, []
    for region in cfg().regions:
        for var in ("precip", "tmax"):
            p = root() / "products" / region / var / "latest.json"
            products[f"{region}/{var}"] = (
                json.loads(p.read_text())["init_time"] if p.exists() else None
            )
    if not any(products.values()):
        notes.append("no live products yet")
    return S.Health(
        status="ok" if all(products.values()) else "degraded", products=products, notes=notes
    )


@app.get("/v1/sources", response_model=S.Sources)
def sources():
    c = cfg()
    runs = root() / "processed" / "archive" / "runs.jsonl"
    last: dict[str, dict] = {}
    if runs.exists():
        for line in runs.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            last[r["source"]] = r
    by_source: dict[str, list] = {}
    for name, a in c.adapters.items():
        by_source.setdefault(a.source, []).append((name, a))
    out = []
    for src, ads in by_source.items():
        kind = ads[0][1].kind
        adapters = [n for n, _ in ads]
        if any(a.type == "ncum" for _, a in ads):
            status, detail = "not_configured", "NCMRWF NCUM/NEPS output is not public"
        else:
            arch = next((a.archive_source for _, a in ads if a.archive_source), None)
            r = last.get(arch or src)
            if r is None:
                status, detail = (
                    ("ok", "history via dynamical.org / Previous Runs")
                    if not arch
                    else ("unknown", "")
                )
            else:
                status = {"ok": "ok", "exists": "ok", "stale": "stale", "failed": "failed"}.get(
                    r["status"], "unknown"
                )
                detail = r.get("detail", "")
        months = []
        for n, a in ads:
            if a.use == "eval":
                months += sorted(
                    p.stem
                    for p in (root() / "processed" / "canonical" / n).glob("*/*.zarr")
                    if p.stem.isdigit()
                )
        out.append(
            S.SourceStatus(
                source=src,
                label=SOURCE_LABELS.get(src, src),
                kind=kind,
                adapters=adapters,
                status=status,
                detail=detail[:300],
                last_archived_init=(last.get(src) or {}).get("init_time"),
                eval_first_init=f"{min(months)[:4]}-{min(months)[4:]}" if months else None,
                eval_last_init=f"{max(months)[:4]}-{max(months)[4:]}" if months else None,
                licence="CC BY 4.0" if src != "ncmrwf_ncum" else "not available",
            )
        )
    return S.Sources(sources=out)


@app.get("/v1/forecast/grid", response_model=S.GridLayer)
def forecast_grid(
    region: str,
    variable: S.Variable = "precip",
    lead_day: int = 1,
    layer: str = "final",
    init: str | None = None,
):
    stem = resolve_init(region, variable, init)
    ds = open_product(region, variable, stem)
    li = lead_index(ds, lead_day)
    layers = ["final", "consensus", "disagreement"] + [
        v for v in ds.data_vars if v.startswith(("prob_", "lo90", "hi90"))
    ]
    layers += [f"source:{s}" for s in ds.source.values] + ["defer"]
    if layer.startswith("source:"):
        s = layer.split(":", 1)[1]
        if s not in ds.source.values:
            raise HTTPException(404, f"unknown source {s!r}")
        da = ds["source_value"].sel(source=s)
    elif layer in ds.data_vars and layer not in ("weights", "dmse", "source_value", "regime"):
        da = ds[layer]
    else:
        raise HTTPException(404, f"unknown layer {layer!r}; available: {layers}")
    da = da.isel(lead_h=li).astype(float)
    vals = [[_f(v) for v in row] for row in da.values]
    finite = da.values[np.isfinite(da.values)]
    return S.GridLayer(
        region=region,
        variable=variable,
        layer=layer,
        units="probability" if layer.startswith("prob_") else UNITS[variable],
        init_time=pd.Timestamp(ds.attrs["init_time"]).to_pydatetime(),
        lead_day=lead_day,
        valid_day=valid_day_of(ds, li, variable),
        lats=[float(x) for x in ds.lat.values],
        lons=[float(x) for x in ds.lon.values],
        values=vals,
        vmin=_f(finite.min()) if finite.size else None,
        vmax=_f(finite.max()) if finite.size else None,
        available_layers=layers,
    )


@app.get("/v1/forecast/blend", response_model=S.PointForecast)
def forecast_point(
    lat: float, lon: float, variable: S.Variable = "precip", init: str | None = None
):
    region = region_of(lat, lon)
    stem = resolve_init(region, variable, init)
    ds = open_product(region, variable, stem)
    land = np.isfinite(ds["final"]).any("lead_h")
    la, lo = np.meshgrid(ds.lat.values, ds.lon.values, indexing="ij")
    d2 = (la - lat) ** 2 + ((lo - lon) * np.cos(np.deg2rad(lat))) ** 2
    d2[~land.values] = np.inf
    if not np.isfinite(d2).any():
        raise HTTPException(404, "no land cell with data")
    i, j = np.unravel_index(np.argmin(d2), d2.shape)
    leads = []
    for li in range(ds.sizes["lead_h"]):
        c = ds.isel(lead_h=li, lat=i, lon=j)
        probs = {
            v.removeprefix("prob_ge_"): _f(c[v]) for v in ds.data_vars if v.startswith("prob_ge_")
        }
        leads.append(
            S.LeadValue(
                lead_day=li + 1,
                valid_day=valid_day_of(ds, li, variable),
                value=_f(c["final"]),
                lo90=_f(c["lo90"]) if "lo90" in ds else None,
                hi90=_f(c["hi90"]) if "hi90" in ds else None,
                prob=probs,
                sources={str(s): _f(c["source_value"].sel(source=s)) for s in ds.source.values},
                weights={
                    str(s): round(float(c["weights"].sel(source=s)), 4) for s in ds.source.values
                },
                regime=str(ds["regime"].values[li]),
                defer=bool(c["defer"]),
            )
        )
    return S.PointForecast(
        region=region,
        variable=variable,
        units=UNITS[variable],
        init_time=pd.Timestamp(ds.attrs["init_time"]).to_pydatetime(),
        lat=lat,
        lon=lon,
        cell_lat=float(ds.lat.values[i]),
        cell_lon=float(ds.lon.values[j]),
        leads=leads,
    )


@app.get("/v1/skill/map", response_model=S.SkillMap)
def skill_map(
    region: str, variable: S.Variable = "precip", lead_day: int = 1, init: str | None = None
):
    stem = resolve_init(region, variable, init)
    ds = open_product(region, variable, stem)
    li = lead_index(ds, lead_day)
    dm = ds["dmse"].isel(lead_h=li)
    cells = []
    for i, la in enumerate(ds.lat.values):
        for j, lo in enumerate(ds.lon.values):
            v = dm.isel(lat=i, lon=j).values
            if not np.isfinite(ds["final"].isel(lead_h=li, lat=i, lon=j).values):
                continue
            best = str(ds.source.values[int(np.nanargmin(v))]) if np.isfinite(v).any() else None
            cells.append(
                S.SkillCell(
                    lat=float(la),
                    lon=float(lo),
                    best_source=best,
                    dmse={str(s): _f(x) for s, x in zip(ds.source.values, v, strict=True)},
                )
            )
    sel = (
        yaml.safe_load((REPO_ROOT / "config" / "model_selection.yaml").read_text())
        if (REPO_ROOT / "config" / "model_selection.yaml").exists()
        else {}
    )
    hl = (sel.get("models", {}).get(f"{region}_{variable}", {}) or {}).get(
        "half_life", float("nan")
    )
    return S.SkillMap(
        region=region,
        variable=variable,
        lead_day=lead_day,
        init_time=pd.Timestamp(ds.attrs["init_time"]).to_pydatetime(),
        half_life_days=hl if hl == hl else 0.0,
        cells=cells,
    )


@app.get("/v1/skill/leaderboard", response_model=S.Leaderboard)
def leaderboard(region: str, variable: S.Variable = "precip", sample: str = "main"):
    p = reports() / "phase2" / "scoreboard_full.csv"
    if not p.exists():
        raise HTTPException(503, "scoreboard not generated yet (scripts/run_verification.py)")
    sb = pd.read_csv(p)
    sb = sb[
        (sb.region == region)
        & (sb.variable == variable)
        & (sb["sample"] == sample)
        & (sb.season == "all")
    ]
    if sb.empty:
        raise HTTPException(404, "no scoreboard rows for this selection")
    t = EVENT_T[variable]
    recent = {}
    try:
        ds = open_product(region, variable, resolve_init(region, variable, None))
        for s in ds.source.values:
            recent[str(s)] = [
                _f(np.sqrt(ds["dmse"].sel(source=s).isel(lead_h=li).mean()))
                for li in range(ds.sizes["lead_h"])
            ]
    except HTTPException:
        pass
    rows = []
    for r in sb.to_dict("records"):
        rows.append(
            S.LeaderboardRow(
                source=r["forecast"],
                kind=r["kind"],
                lead_day=int(r["lead_day"]),
                rmse=_f(r["rmse"]),
                rmse_lo=_f(r["rmse_lo"]),
                rmse_hi=_f(r["rmse_hi"]),
                crps=_f(r["crps"]),
                ets_heavy=_f(r.get(f"ets_{t}")),
                n_cases=int(r["n_cases"]),
                recent_rmse=(recent.get(r["forecast"]) or [None] * 9)[int(r["lead_day"]) - 1],
            )
        )
    vd = (
        pd.read_csv(reports() / "phase2" / "coverage.csv")
        if (reports() / "phase2" / "coverage.csv").exists()
        else None
    )
    period = (
        "development split (2024-2025), valid days from 2024-04-01"
        if sample == "main"
        else "from 2025-07-02"
    )
    if vd is not None:
        period += "; see coverage.csv"
    return S.Leaderboard(region=region, variable=variable, sample=sample, period=period, rows=rows)


@app.get("/v1/verification/summary", response_model=S.VerificationSummary)
def verification_summary():
    phases, notes = {}, []
    sel_p = REPO_ROOT / "config" / "model_selection.yaml"
    if sel_p.exists():
        phases["model_selection"] = yaml.safe_load(sel_p.read_text())
    for ph in ("phase2", "phase3", "phase4", "phase5", "phase8"):
        d = reports() / ph
        phases[ph] = {"files": sorted(p.name for p in d.glob("*"))} if d.exists() else {"files": []}
    sb = reports() / "phase2" / "SCOREBOARD.md"
    gen = None
    if sb.exists():
        for line in sb.read_text(encoding="utf-8").splitlines():
            if line.startswith("Generated"):
                gen = line
                break
    notes.append("Development-split results; the frozen 2026 test is run once in Phase 8.")
    return S.VerificationSummary(phases=phases, scoreboard_generated=gen, notes=notes)


@app.get("/v1/alerts/district", response_model=S.Alerts)
def alerts(
    region: str, variable: S.Variable = "precip", init: str | None = None, min_level: str = "yellow"
):
    stem = resolve_init(region, variable, init)
    payload = open_districts(region, variable, stem)
    order = ["none", "yellow", "orange", "red"]
    t = EVENT_T[variable]
    out = []
    for d in payload["districts"]:
        for ld in d["leads"]:
            p = ld["probabilities"].get(t)
            lvl = alert_level(p)
            if order.index(lvl) >= order.index(min_level):
                out.append(
                    S.DistrictAlert(
                        district_id=d["district_id"],
                        district=d["district"],
                        state=d["state"],
                        lead_day=ld["lead_day"],
                        valid_day=ld["valid_day"],
                        level=lvl,
                        event="heavy rain >= 64.5 mm" if variable == "precip" else "Tmax >= 40 C",
                        probability=p,
                        value=ld["value"],
                        defer=ld["defer"],
                        coverage=d.get("coverage", 1.0),
                    )
                )
    return S.Alerts(
        region=region,
        variable=variable,
        init_time=pd.Timestamp(payload["init_time"]).to_pydatetime(),
        rule="probability >= 0.2 yellow, >= 0.4 orange, >= 0.7 red (decision-support rule)",
        alerts=out,
    )


@app.get("/v1/explain/{district_id}", response_model=S.Explanation)
def explain(
    district_id: str, variable: S.Variable = "precip", lead_day: int = 1, init: str | None = None
):
    _, _, payload, d = find_district(district_id, variable, init)
    ld = next((x for x in d["leads"] if x["lead_day"] == lead_day), None)
    if ld is None:
        raise HTTPException(422, "lead_day out of range")
    method = (
        "gated blend (LightGBM gate, SHAP of the gate)"
        if payload["meta"].get("gate")
        else "decayed-skill blend (weights from recent verified skill)"
    )
    return S.Explanation(
        district_id=district_id,
        district=d["district"],
        state=d["state"],
        variable=variable,
        init_time=pd.Timestamp(payload["init_time"]).to_pydatetime(),
        lead_day=lead_day,
        valid_day=ld["valid_day"],
        value=ld["value"],
        lo90=ld.get("lo90"),
        hi90=ld.get("hi90"),
        probabilities=ld["probabilities"],
        weights=ld["weights"],
        top_features=[tuple(x) for x in ld["top_features"]],
        regime=ld["regime"],
        defer=ld["defer"],
        sentence=ld["sentence"],
        method=method,
    )


@app.get("/v1/bulletin/{district_id}", response_model=S.Bulletin)
def bulletin(
    district_id: str,
    variable: S.Variable = "precip",
    lang: str = Query("en", pattern="^(en|hi)$"),
    init: str | None = None,
):
    _, _, payload, d = find_district(district_id, variable, init)
    con = connect(root() / "app" / "overrides.sqlite")
    ov = load_overrides(con, variable)
    ov = ov[ov.district_id == district_id] if len(ov) else ov
    override = ov.iloc[-1].to_dict() if len(ov) else None
    text = render(d, variable, lang, override)
    nums = bulletin_numbers(d, variable)
    ignore = (override["reason"], str(override["valid_day"])) if override else ()
    errors = validate(text, nums, ignore=ignore)
    return S.Bulletin(
        district_id=district_id,
        language=lang,
        init_time=pd.Timestamp(payload["init_time"]).to_pydatetime(),
        text=text,
        numbers=nums,
        validated=not errors,
        validation_errors=errors,
    )


@app.get("/v1/alerts/cap/{district_id}")
def cap(
    district_id: str, variable: S.Variable = "precip", lead_day: int = 1, init: str | None = None
):
    region, _, _, d = find_district(district_id, variable, init)
    ld = next((x for x in d["leads"] if x["lead_day"] == lead_day), None)
    if ld is None:
        raise HTTPException(422, "lead_day out of range")
    p = ld["probabilities"].get(EVENT_T[variable])
    level = alert_level(p)
    geo = root() / "processed" / "static" / f"districts_{region}.geojson"
    poly = None
    if geo.exists():
        feat = next(
            (
                f
                for f in json.loads(geo.read_text(encoding="utf-8"))["features"]
                if f["properties"]["district_id"] == district_id
            ),
            None,
        )
        if feat is not None:
            g = feat["geometry"]
            ring = (
                g["coordinates"][0]
                if g["type"] == "Polygon"
                else max(g["coordinates"], key=lambda r: len(r[0]))[0]
            )
            poly = [(pt[1], pt[0]) for pt in ring]
    day = pd.Timestamp(ld["valid_day"])
    onset = (day - pd.Timedelta(hours=21)).to_pydatetime().replace(tzinfo=dt.UTC)
    xml = build_cap(
        d["district"],
        d["state"],
        "Heavy rain (decision support)"
        if variable == "precip"
        else "Extreme heat (decision support)",
        level,
        p or 0.0,
        onset,
        onset + dt.timedelta(days=1),
        poly,
        f"{d['district']}: {level} level, day {lead_day}",
        ld["sentence"],
    )
    return Response(content=xml, media_type="application/xml")


@app.get("/v1/replay/{event_id}", response_model=S.Replay)
def replay(event_id: str):
    p = root() / "replays" / f"{event_id}.json"
    if not p.exists():
        idx = sorted(x.stem for x in (root() / "replays").glob("*.json"))
        raise HTTPException(404, f"unknown event {event_id!r}; available: {idx}")
    return S.Replay(**json.loads(p.read_text(encoding="utf-8")))


@app.get("/v1/replay")
def replay_index():
    folder = root() / "replays"
    items = []
    for p in sorted(folder.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        items.append(
            {
                "event_id": d["event_id"],
                "title": d["title"],
                "focus_day": d["focus_day"],
                "district_id": d["district_id"],
                "variable": d["variable"],
            }
        )
    return {"disclaimer": DISCLAIMER, "events": items}


@app.post("/v1/feedback/override", response_model=S.OverrideOut)
def post_override(body: S.OverrideIn):
    con = connect(root() / "app" / "overrides.sqlite")
    oid = add_override(
        con,
        body.district_id,
        body.variable,
        body.valid_day,
        body.value,
        body.distrust_sources,
        body.reason,
        body.author,
    )
    effect = "stored; shown with the district product and bulletins; " + (
        f"DMSE of {', '.join(body.distrust_sources)} in this district is penalised for later inits "
        "(x2 decaying with a 7-day half-life), lowering their blend weights"
        if body.distrust_sources
        else "no source penalty requested"
    )
    return S.OverrideOut(id=oid, stored=body, effect=effect)


@app.get("/v1/meta/regions")
def meta_regions():
    out = {}
    for name, r in cfg().regions.items():
        geo = root() / "processed" / "static" / f"districts_{name}.geojson"
        out[name] = {
            "label": r.label,
            "lat": r.lat,
            "lon": r.lon,
            "districts": json.loads(geo.read_text(encoding="utf-8")) if geo.exists() else None,
        }
    return {"disclaimer": DISCLAIMER, "regions": out}
