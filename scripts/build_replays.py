"""Build event replays (config/replays.yaml): single models vs the blend vs IMD, by lead day.

    python scripts/build_replays.py
    python scripts/build_replays.py --events wayanad_2024

For each event the full pipeline is run with the production configuration over the development data;
learned layers only exist from their first training quarter, so each replay states which layers were
active at the event time. Output: data/replays/<event_id>.json (served by /v1/replay/{event_id}).
Development-period events only (valid days < 2026-01-01).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trustcast import DISCLAIMER
from trustcast.blend.baselines import equal_mean
from trustcast.config import data_root, load_config
from trustcast.grid.districts import district_means, district_table
from trustcast.grid.static import static_features
from trustcast.pipeline import config_from_selection, run_pipeline
from trustcast.verify.assemble import assemble, climatology, frozen_sources
from trustcast.verify.data import TRUTH_DAY_OFFSET

MIN_CELLS = 3
MIN_COVERAGE = 0.5


def _series(
    da: xr.DataArray, table: pd.DataFrame, did: str, days: pd.DatetimeIndex, off: int
) -> dict:
    """{lead_day: {day: value}} of a forecast field for one district (day = observation day)."""
    dm = district_means(da.drop_vars("valid_day", errors="ignore"), table[table.district_id == did])
    vd = pd.DatetimeIndex(da["valid_day"].values.ravel()).to_numpy().reshape(da["valid_day"].shape)
    out: dict[int, dict[str, float | None]] = {}
    inits = list(da.init_time.values)
    for r in dm.itertuples():
        i, li = inits.index(r.init_time), list(da.lead_h.values).index(r.lead_h)
        day = pd.Timestamp(vd[i, li]) + pd.Timedelta(days=off)
        if day in days:
            v = None if not np.isfinite(r.value) else round(float(r.value), 2)
            out.setdefault(li + 1, {})[str(day.date())] = v
    return out


def build(cfg, root, event_id: str, ev: dict) -> Path:
    b = assemble(
        cfg,
        root,
        ev["region"],
        ev["variable"],
        sources=frozen_sources(ev["region"], ev["variable"]),
    )
    table, _ = district_table(cfg, root, ev["region"])
    off = TRUTH_DAY_OFFSET[ev["variable"]]
    s0, s1 = pd.Timestamp(ev["search"][0]), pd.Timestamp(ev["search"][1])
    obs_d = district_means(
        b.truth.sel(time=slice(s0 - pd.Timedelta(days=10), s1 + pd.Timedelta(days=10))), table
    )
    win = obs_d[(obs_d.time >= s0) & (obs_d.time <= s1)]
    # data-driven choice only among districts that are mostly inside the region and not tiny enclaves
    size = table.groupby("district_id").agg(n=("weight", "size"), cov=("coverage", "first"))
    eligible = size[(size.n >= MIN_CELLS) & (size["cov"] >= MIN_COVERAGE)].index
    if not ev.get("district_id"):
        win = win[win.district_id.isin(eligible)]
    if ev.get("district_id"):
        win = win[win.district_id == ev["district_id"]]
    best = win.loc[win.value.idxmax()]
    did, focus = str(best.district_id), pd.Timestamp(best.time)
    half = ev.get("window_days", 5)
    days = pd.date_range(focus - pd.Timedelta(days=half), focus + pd.Timedelta(days=half))
    observed = {
        str(d.date()): (None if not np.isfinite(v) else round(float(v), 2))
        for d, v in obs_d[obs_d.district_id == did].set_index("time").value.reindex(days).items()
    }
    land = np.isfinite(b.truth).any("time")
    pc, provenance = config_from_selection(ev["region"], ev["variable"])
    res = run_pipeline(
        b,
        pc,
        climatology(cfg, root, ev["region"], ev["variable"]),
        static_features(cfg, root, ev["region"], land.values),
    )
    sl = {"init_time": slice(days[0] - pd.Timedelta(days=6), days[-1])}
    fcs = {
        "trustcast": res.final_det.sel(sl),
        "equal_mean": equal_mean({f.name: f.det.where(land) for f in b.forecasts})
        .assign_coords(valid_day=b.like.valid_day)
        .sel(sl),
    }
    for f in b.forecasts:
        fcs[f.name] = f.det.where(land).sel(sl)
    series = [
        {"forecast": name, "lead_day": lead, "values": vals}
        for name, da in fcs.items()
        for lead, vals in sorted(_series(da, table, did, days, off).items())
    ]
    notes = [
        f"District chosen from IMD observations: {did}, peak on {focus.date()} "
        f"({observed[str(focus.date())]} {'mm' if ev['variable'] == 'precip' else 'degC'}).",
        f"Configuration: {provenance}.",
        f"Learned layers (gate, event classifiers, quantile models) start at inits >= {pc.learn_start.date()}; "
        + (
            "they were NOT yet trained at this event, so TRUSTCAST here = bias-corrected decayed-skill blend."
            if focus < pc.learn_start
            else "they were active at this event."
        ),
        "Sources without data for these dates are absent (nothing is substituted).",
        DISCLAIMER,
    ]
    if res.probs and ev["variable"] == "precip":
        p = res.probs[64.5].sel(sl)
        ps = _series(p, table, did, pd.DatetimeIndex([focus]), off)
        if ps:
            notes.insert(
                1,
                "P(>= 64.5 mm) for the focus day by lead: "
                + ", ".join(
                    f"day {k}: {'n/a' if v.get(str(focus.date())) is None else f'{100 * v[str(focus.date())]:.0f} %'}"
                    for k, v in sorted(ps.items())
                ),
            )
    out = {
        "event_id": event_id,
        "title": ev["title"],
        "region": ev["region"],
        "variable": ev["variable"],
        "district_id": did,
        "focus_day": str(focus.date()),
        "observed": observed,
        "series": series,
        "notes": notes,
        "disclaimer": DISCLAIMER,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
    }
    p = root / "replays" / f"{event_id}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return p


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--events", nargs="+", default=None)
    args = ap.parse_args()
    cfg = load_config()
    root = data_root()
    events = yaml.safe_load((REPO / "config" / "replays.yaml").read_text())["events"]
    for eid, ev in events.items():
        if args.events and eid not in args.events:
            continue
        print(f"{eid}: {build(cfg, root, eid, ev)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
