"""District aggregation on the IMD 0.25 deg grid.

Boundaries: geoBoundaries gbOpen India ADM2 (2021, 735 features; source Pathways Data / LGD
directory; ODbL 1.0) and ADM1 states (DataMeet / Election Commission of India; CC BY 2.5 IN),
simplified
GeoJSON under ``data/static/``. Each district is linked to the grid cells it overlaps with weights
equal to the overlap area (in degree^2 x cos(lat)); district values are weighted means over cells
with data. The state of a district is the ADM1 polygon containing its representative point.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from shapely import STRtree
from shapely.geometry import box, mapping, shape

from trustcast.config import Config
from trustcast.grid.imd_grid import IMD_RAIN_0P25

ADM2 = "geoBoundaries-IND-ADM2_simplified.geojson"
ADM1 = "geoBoundaries-IND-ADM1_simplified.geojson"
LICENCE = (
    "District boundaries: geoBoundaries (Runfola et al. 2020), India ADM2 from Pathways Data / "
    "LGD, ODbL 1.0; states: DataMeet / ECI, CC BY 2.5 IN"
)


def _slug(name: str, state: str) -> str:
    return f"{state}-{name}".lower().replace(" ", "-").replace("&", "and").replace(".", "")


def district_table(cfg: Config, root: Path, region: str) -> tuple[pd.DataFrame, dict]:
    """(cell weights table, GeoJSON FeatureCollection) of districts overlapping the region.

    Table columns: district_id, district, state, lat, lon, weight. Cached under processed/static/.
    """
    cache = root / "processed" / "static" / f"districts_{region}.parquet"
    gcache = root / "processed" / "static" / f"districts_{region}.geojson"
    if cache.exists() and gcache.exists():
        return pd.read_parquet(cache), json.loads(gcache.read_text(encoding="utf-8"))
    static = root / "static"
    adm2 = json.loads((static / ADM2).read_text(encoding="utf-8"))["features"]
    adm1 = json.loads((static / ADM1).read_text(encoding="utf-8"))["features"]
    states = [(shape(f["geometry"]), f["properties"]["shapeName"]) for f in adm1]
    lats, lons = IMD_RAIN_0P25.region_points(cfg.regions[region])
    h = IMD_RAIN_0P25.step / 2
    cells = [(la, lo, box(lo - h, la - h, lo + h, la + h)) for la in lats for lo in lons]
    region_box = box(lons.min() - h, lats.min() - h, lons.max() + h, lats.max() + h)
    tree = STRtree([c[2] for c in cells])
    rows, feats = [], []
    for f in adm2:
        geom = shape(f["geometry"])
        if not geom.intersects(region_box):
            continue
        name = f["properties"]["shapeName"]
        rp = geom.representative_point()
        state = next((s for g, s in states if g.contains(rp)), "unknown")
        did = _slug(name, state)
        hits = tree.query(geom)
        total = 0.0
        first_row = len(rows)
        for i in hits:
            la, lo, cb = cells[int(i)]
            a = geom.intersection(cb).area * np.cos(np.deg2rad(la))
            if a > 0:
                rows.append(
                    {
                        "district_id": did,
                        "district": name,
                        "state": state,
                        "lat": float(la),
                        "lon": float(lo),
                        "weight": float(a),
                    }
                )
                total += a
        # share of the district's area inside the pilot region (values use only that part)
        coverage = min(1.0, total / (geom.area * np.cos(np.deg2rad(rp.y))))
        for r in rows[first_row:]:
            r["coverage"] = round(coverage, 3)
        clipped = geom.intersection(region_box)
        if total > 0 and not clipped.is_empty:
            feats.append(
                {
                    "type": "Feature",
                    "geometry": mapping(clipped.simplify(0.01)),
                    "properties": {
                        "district_id": did,
                        "district": name,
                        "state": state,
                        "coverage": round(coverage, 3),
                    },
                }
            )
    table = pd.DataFrame(rows)
    fc = {"type": "FeatureCollection", "features": feats, "licence": LICENCE}
    cache.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(cache, index=False)
    gcache.write_text(json.dumps(fc), encoding="utf-8")
    return table, fc


def district_means(field: xr.DataArray, table: pd.DataFrame) -> pd.DataFrame:
    """Area-weighted district means of a (..., lat, lon) field; returns long table.

    Output columns: district_id plus the non-spatial dims of ``field`` and ``value``.
    """
    other = [d for d in field.dims if d not in ("lat", "lon")]
    stacked = field.stack(cell=("lat", "lon")).transpose(*other, "cell")
    lat = stacked["lat"].values
    lon = stacked["lon"].values
    idx = {
        (round(float(a), 4), round(float(b), 4)): k
        for k, (a, b) in enumerate(zip(lat, lon, strict=True))
    }
    vals = stacked.values.reshape(-1, stacked.sizes["cell"])
    out = []
    for did, g in table.groupby("district_id"):
        cols = [idx[(round(a, 4), round(b, 4))] for a, b in zip(g.lat, g.lon, strict=True)]
        w = g.weight.to_numpy()
        v = vals[:, cols]
        ok = np.isfinite(v)
        with np.errstate(all="ignore"):
            m = np.where(ok.any(1), (np.where(ok, v, 0) * w).sum(1) / (ok * w).sum(1), np.nan)
        out.append(pd.DataFrame({"district_id": did, "value": m}))
        if other:
            coords = pd.MultiIndex.from_product(
                [stacked[d].values for d in other], names=other
            ).to_frame(index=False)
            out[-1] = pd.concat([coords, out[-1]], axis=1)
    return pd.concat(out, ignore_index=True)
