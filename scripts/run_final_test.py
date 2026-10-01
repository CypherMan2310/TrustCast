"""Phase 8: the frozen held-out test (Jan-Sep 2026). Runs ONCE.

    python scripts/run_final_test.py --dry-run                      # check preconditions only
    python scripts/run_final_test.py                                # the one real run
    python scripts/run_final_test.py --allow-provisional-truth      # if IMD 2026 is still missing

Rules (CLAUDE.md rule 3): hyperparameters and layer choices come from config/model_selection.yaml,
which was produced on the development split only. This script never tunes. The first real run writes
reports/phase8/FINAL_LOCK.json (git commit, model_selection hash, data coverage); later runs refuse.
Outputs: reports/phase8/FINAL.md and CSVs, including before/after the ECMWF change (IFS Cy50r1 +
AIFS v2, 12 May 2026).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
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
from trustcast.archive.manifest import git_version
from trustcast.config import data_root, load_config
from trustcast.grid.static import static_features
from trustcast.pipeline import config_from_selection, run_pipeline
from trustcast.truth import imd
from trustcast.verify.assemble import assemble, baselines, climatology, frozen_sources
from trustcast.verify.scoreboard import Forecast, overall, scoreboard

OUT = REPO / "reports" / "phase8"
LOCK = OUT / "FINAL_LOCK.json"


def preconditions(cfg, root, raw: dict) -> tuple[list[str], dict]:
    """Problems that block the run, and a coverage summary."""
    problems, cov = [], {}
    if not (REPO / "config" / "model_selection.yaml").exists():
        problems.append("config/model_selection.yaml missing: run scripts/run_experiments.py first")
    t0, t1 = pd.Timestamp(raw["start"]), pd.Timestamp(raw["end"])
    want = pd.date_range(t0, t1 - pd.Timedelta(days=cfg.canonical.lead_days), freq="D")
    for name, a in cfg.adapters.items():
        if a.use != "eval" or a.type == "ncum":
            continue
        for region in cfg.regions:
            # only the sources frozen with the model settings are needed (and scored)
            frozen = {s for v in ("precip", "tmax") for s in (frozen_sources(region, v) or [])}
            if frozen and a.source not in frozen:
                continue
            n = 0
            for p in (root / "processed" / "canonical" / name / region).glob("2026*.zarr"):
                with xr.open_zarr(p, consolidated=False) as ds:
                    n += int(np.isin(pd.DatetimeIndex(ds.init_time.values), want).sum())
            cov[f"{name}/{region}"] = round(n / len(want), 3)
    days = pd.date_range(t0, t1)
    final = set(imd.available_days(root, "rain", [2026]))
    realtime = {d for d in days if imd.realtime_path(root, "rain", d).exists()}
    cov["imd_rain_2026_fraction"] = round(
        float(np.mean([d in final or d in realtime for d in days])), 3
    )
    cov["imd_rain_2026_final_fraction"] = round(float(np.mean([d in final for d in days])), 3)
    # GEM stopped on 2026-05-26 at the provider, so it cannot reach full coverage
    low = [k for k, v in cov.items() if "/" in k and v < 0.8 and not k.startswith("gem_prev")]
    if low:
        problems.append(f"test-period forecast coverage below 80 % for: {low}")
    return problems, cov


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-provisional-truth", action="store_true")
    ap.add_argument("--n-boot", type=int, default=1000)
    args = ap.parse_args()
    cfg = load_config()
    root = data_root()
    raw = yaml.safe_load((REPO / "config" / "pilot.yaml").read_text(encoding="utf-8"))[
        "frozen_test"
    ]
    if LOCK.exists():
        print(f"REFUSED: the frozen test has already been run ({LOCK}).")
        return 2
    problems, cov = preconditions(cfg, root, raw)
    if cov["imd_rain_2026_fraction"] < 1.0 and not args.allow_provisional_truth:
        problems.append(
            f"IMD 2026 rain (final or real-time) covers only {cov['imd_rain_2026_fraction']:.0%} of test "
            "days (the rest would be IMERG satellite); pass --allow-provisional-truth to accept and record this"
        )
    print(json.dumps({"coverage": cov, "problems": problems}, indent=1))
    if args.dry_run:
        print("dry run: nothing scored, nothing locked")
        return 0
    if problems:
        print("BLOCKED: fix the problems above")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    sel_hash = hashlib.sha256((REPO / "config" / "model_selection.yaml").read_bytes()).hexdigest()
    LOCK.write_text(
        json.dumps(
            {
                "started_at": dt.datetime.now(dt.UTC).isoformat(),
                "git": git_version(),
                "model_selection_sha256": sel_hash,
                "coverage": cov,
                "provisional_truth_allowed": args.allow_provisional_truth,
            },
            indent=1,
        )
    )
    t0, t1 = pd.Timestamp(raw["start"]), pd.Timestamp(raw["end"])
    change = pd.Timestamp(raw["ecmwf_change"])
    boards = []
    md = [
        "# Phase 8: frozen test (Jan-Sep 2026), run once",
        "",
        f"> {DISCLAIMER}",
        "",
        f"Git {git_version()}; model_selection.yaml sha256 {sel_hash[:12]}; rain truth: IMD on "
        f"{cov['imd_rain_2026_fraction']:.0%} of days, else IMERG provisional.",
        "",
    ]
    for region in cfg.regions:
        for var in ("precip", "tmax"):
            b = assemble(
                cfg, root, region, var, allow_test=True, sources=frozen_sources(region, var)
            )
            if b is None:
                continue
            land = np.isfinite(b.truth).any("time")
            pc, prov = config_from_selection(region, var)
            res = run_pipeline(
                b,
                pc,
                climatology(cfg, root, region, var),
                static_features(cfg, root, region, land.values),
            )
            base, ref_prob = baselines(cfg, root, b)
            fcs = [
                res.forecast("trustcast"),
                *[
                    f
                    for f in base
                    if f.name in ("equal_mean", "superensemble", "climatology", "persistence")
                ],
                *[Forecast(f.name, "source", f.det.where(land), f.ens) for f in b.forecasts],
            ]
            for sample, w0, w1 in (
                ("test", t0, t1),
                ("test_pre_ecmwf_change", t0, change - pd.Timedelta(days=1)),
                ("test_post_ecmwf_change", change, t1),
            ):
                boards.append(
                    scoreboard(
                        fcs,
                        b.obs,
                        var,
                        region,
                        "equal_mean",
                        ref_prob,
                        n_boot=args.n_boot,
                        sample=sample,
                        window=(w0, w1),
                        common=False,
                        regimes=res.regimes,
                    )
                )
            md.append(f"- {region} {var}: configuration {prov}")
    sb = pd.concat(boards, ignore_index=True)
    sb.to_csv(OUT / "scoreboard_test.csv", index=False, float_format="%.5g")
    allr = overall(sb[sb["sample"] == "test"])
    cols = [
        "region",
        "variable",
        "forecast",
        "lead_day",
        "n_cases",
        "rmse",
        "rmse_lo",
        "rmse_hi",
        "d_rmse_vs_ref",
        "d_rmse_lo",
        "d_rmse_hi",
    ]
    md += [
        "",
        "## RMSE by lead (95 % CI) and paired difference vs the equal-weight mean",
        "",
        allr[cols].to_markdown(index=False, floatfmt=".3f"),
        "",
        "Before/after the ECMWF change: scoreboard_test.csv, samples test_pre_/test_post_ecmwf_change.",
        "Each forecast is scored on its own available cases (the source set changes during 2026); "
        "paired differences use common cases.",
        "",
    ]
    (OUT / "FINAL.md").write_text("\n".join(md), encoding="utf-8")
    lock = json.loads(LOCK.read_text())
    lock["finished_at"] = dt.datetime.now(dt.UTC).isoformat()
    LOCK.write_text(json.dumps(lock, indent=1))
    print(f"frozen test written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
