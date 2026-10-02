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
from trustcast.truth.build import SRC_IMERG
from trustcast.verify.assemble import assemble, baselines, climatology, frozen_sources
from trustcast.verify.compare import brier_compare, coverage_by_lead, defer_stats, window_mask
from trustcast.verify.data import load_truth
from trustcast.verify.scoreboard import THRESHOLDS, Forecast, overall, scoreboard

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
    ap.add_argument(
        "--rehearsal",
        action="store_true",
        help="run the same scoring code on the 2025 dev window (no test data read, no lock)",
    )
    args = ap.parse_args()
    cfg = load_config()
    root = data_root()
    if args.rehearsal:
        out = root / "processed" / "rehearsal_phase8"
        score_window(
            cfg,
            root,
            pd.Timestamp("2025-01-01"),
            pd.Timestamp("2025-09-30"),
            pd.Timestamp("2025-05-13"),
            False,
            args.n_boot,
            out,
            "REHEARSAL on the 2025 dev window (code check only; NOT the frozen test)",
            ["Same code as the frozen test, on development data the settings were tuned on."],
        )
        print(f"rehearsal written to {out}")
        return 0
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
    header = [
        f"Git {git_version()}; model_selection.yaml sha256 {sel_hash[:12]}; rain truth: IMD (final or "
        f"real-time gauge grid) on {cov['imd_rain_2026_fraction']:.0%} of days, else IMERG (provisional);"
        " provisional truth accepted: " + str(args.allow_provisional_truth) + ".",
    ]
    score_window(
        cfg,
        root,
        t0,
        t1,
        pd.Timestamp(raw["ecmwf_change"]),
        True,
        args.n_boot,
        OUT,
        "Phase 8: frozen test (Jan-Sep 2026), run once",
        header,
    )
    lock = json.loads(LOCK.read_text())
    lock["finished_at"] = dt.datetime.now(dt.UTC).isoformat()
    LOCK.write_text(json.dumps(lock, indent=1))
    print(f"frozen test written to {OUT}")
    return 0


def ensemble_fraction(b, land, t):
    """Raw ensemble exceedance fraction averaged over ensemble sources (None without ensembles)."""
    ms = [f.ens.where(land) for f in b.forecasts if f.ens is not None]
    if not ms:
        return None
    fr = [((m >= t).where(np.isfinite(m))).mean("member") for m in ms]
    return xr.concat(fr, dim="e").mean("e", skipna=True)


def imerg_day_mask(root, region: str, b, allow_test: bool) -> xr.DataArray:
    """(init_time, lead_h) True where the rain truth of the valid day is IMERG (satellite)."""
    src = load_truth(root, region, allow_test=allow_test)["rain_source"].load()
    vd = pd.DatetimeIndex(b.like["valid_day"].values.ravel())
    code = src.reindex(time=vd).values.reshape(b.like["valid_day"].shape)
    return xr.DataArray(
        code == SRC_IMERG,
        dims=("init_time", "lead_h"),
        coords={"init_time": b.like.init_time, "lead_h": b.like.lead_h},
    )


def score_window(cfg, root, t0, t1, change, allow_test, n_boot, out_dir, title, header) -> None:
    """Score the frozen configuration on [t0, t1] (also before/after ``change``): RMSE with 95 % CI and
    paired differences, heavy-event skill, probabilities (Brier), interval coverage, defer flag and,
    for rain, an IMD-truth-only sensitivity sample. Never tunes anything."""
    out_dir.mkdir(parents=True, exist_ok=True)
    boards, probs_rows, cov_rows, defer_rows = [], [], [], []
    md = [f"# {title}", "", f"> {DISCLAIMER}", "", *header, ""]
    w = (str(t0.date()), str(t1.date()))
    for region in cfg.regions:
        for var in ("precip", "tmax"):
            b = assemble(
                cfg, root, region, var, allow_test=allow_test, sources=frozen_sources(region, var)
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
            samples = [
                ("test", b.obs, t0, t1),
                ("test_pre_ecmwf_change", b.obs, t0, change - pd.Timedelta(days=1)),
                ("test_post_ecmwf_change", b.obs, change, t1),
            ]
            if var == "precip":
                imerg = imerg_day_mask(root, region, b, allow_test)
                samples.append(("test_imd_truth_only", b.obs.where(~imerg), t0, t1))
            for sample, obs_s, w0, w1 in samples:
                boards.append(
                    scoreboard(
                        fcs,
                        obs_s,
                        var,
                        region,
                        "equal_mean",
                        ref_prob,
                        n_boot=n_boot,
                        sample=sample,
                        window=(w0, w1),
                        common=False,
                        regimes=res.regimes,
                    )
                )
            obs = b.obs.where(land)
            mask = window_mask(b.like, *w)
            key = {"region": region, "variable": var}
            for t in THRESHOLDS[var]:
                if t not in res.probs:
                    continue
                alts = {}
                ens_p = ensemble_fraction(b, land, t)
                if ens_p is not None and res.prob_method != "ensemble_fraction":
                    alts["ensemble_fraction"] = ens_p
                if ref_prob is not None:
                    alts["climatology"] = ref_prob[t].where(land)
                for other, pr in alts.items():
                    r, n, rate = brier_compare(res.probs[t], pr, obs, t, mask, n_boot)
                    probs_rows.append(
                        key
                        | {
                            "threshold": t,
                            "method": res.prob_method,
                            "vs": other,
                            "n": n,
                            "event_rate": rate,
                            "brier": r.score_a,
                            "brier_other": r.score_b,
                            "d_brier": r.diff,
                            "ci_low": r.ci_low,
                            "ci_high": r.ci_high,
                        }
                    )
            if res.lo is not None:
                cv = coverage_by_lead(res.lo, res.hi, obs, mask)
                cov_rows += [key | r for r in cv.to_dict("records")]
            defer_rows.append(key | defer_stats(res.final_det, obs, res.defer, mask))
            md.append(f"- {region} {var}: configuration {prov}; probabilities: {res.prob_method}")
    sb = pd.concat(boards, ignore_index=True)
    sb.to_csv(out_dir / "scoreboard_test.csv", index=False, float_format="%.5g")
    pd.DataFrame(probs_rows).to_csv(out_dir / "brier_test.csv", index=False, float_format="%.5g")
    pd.DataFrame(cov_rows).to_csv(out_dir / "coverage_test.csv", index=False, float_format="%.5g")
    pd.DataFrame(defer_rows).to_csv(out_dir / "defer_test.csv", index=False, float_format="%.5g")
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
    keep = ["trustcast", "equal_mean", "superensemble", "climatology"]
    md += ["", "## RMSE by lead (95 % CI) and paired difference vs the equal-weight mean", ""]
    for sample in sb["sample"].unique():
        allr = overall(sb[sb["sample"] == sample])
        main = allr[allr.forecast.isin(keep)]
        md += [
            f"### Sample `{sample}`",
            "",
            main[cols].to_markdown(index=False, floatfmt=".3f"),
            "",
        ]
    allr = overall(sb[sb["sample"] == "test"])
    main = allr[allr.forecast.isin(keep)]
    ev_cols = [c for c in allr.columns if c.startswith(("ets_", "fbias_", "pod_", "far_"))]
    md += [
        "## Heavy-event skill (rain >= 64.5 / 115.6 mm, Tmax >= 40 degC), sample `test`",
        "",
        main[["region", "variable", "forecast", "lead_day", *ev_cols]]
        .dropna(axis=1, how="all")
        .to_markdown(index=False, floatfmt=".3f"),
        "",
        "## Probabilities: Brier score, paired block bootstrap (negative d_brier = TRUSTCAST better)",
        "",
        pd.DataFrame(probs_rows).to_markdown(index=False, floatfmt=".4f") if probs_rows else "none",
        "",
        "## 90 % interval coverage by lead",
        "",
        pd.DataFrame(cov_rows).to_markdown(index=False, floatfmt=".3f") if cov_rows else "none",
        "",
        "## Defer flag (RMSE of flagged vs unflagged cases)",
        "",
        pd.DataFrame(defer_rows).to_markdown(index=False, floatfmt=".3f"),
        "",
        "Every source and baseline, all strata (season, regime): scoreboard_test.csv. Each forecast is"
        " scored on its own available cases; paired differences use common cases. Sample"
        " `test_imd_truth_only` drops the rain days whose truth is IMERG (satellite).",
        "",
    ]
    (out_dir / "FINAL.md").write_text("\n".join(md), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
