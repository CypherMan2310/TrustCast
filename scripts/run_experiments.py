"""Phases 3-5 on the development split: tune, gate each layer, ablate. One command.

    python scripts/run_experiments.py                     # all regions/variables
    python scripts/run_experiments.py --regions rain_pilot --variables precip --n-boot 300

Protocol (fixed before looking at results; see CLAUDE.md "Verification protocol"):
    tune window      valid days 2024-04-01 .. 2024-12-31  (hyperparameters, temperature)
    holdout window   valid days 2025-01-01 .. 2025-12-31  (every layer gate + ablations)
    learned layers   first predictions for inits >= 2024-10-01 (trained on earlier verified cases)
    gate rule        verify.compare.verdict: RMSE significantly lower at >= 3 of 5 leads, never worse
Frozen 2026 test data are never read (load functions drop valid days >= 2026-01-01).

Outputs: reports/phase3/, reports/phase4/, reports/phase5/ and config/model_selection.yaml.
"""

from __future__ import annotations

import argparse
import datetime as dt
import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trustcast import DISCLAIMER
from trustcast.blend.baselines import equal_mean
from trustcast.blend.decayed import blend_a
from trustcast.blend.features import ORDER, stack_sources
from trustcast.blend.gated import apply_weights
from trustcast.blend.regime import regime_counts
from trustcast.config import data_root, load_config
from trustcast.grid.static import static_features
from trustcast.pipeline import AI_SOURCES, PipelineConfig, run_pipeline
from trustcast.skill.tracker import decayed_mse
from trustcast.verify.assemble import (
    MIN_SOURCE_COVERAGE,
    MIN_SOURCE_DAYS,
    assemble,
    baselines,
    climatology,
    source_coverage,
)
from trustcast.verify.compare import (
    brier_compare,
    coverage_by_lead,
    defer_stats,
    event_verdict,
    pick_forecasts,
    pooled_rmse,
    reliability_rows,
    verdict,
    window_mask,
)
from trustcast.verify.scoreboard import THRESHOLDS, Forecast, overall, scoreboard

TUNE = ("2024-04-01", "2024-12-31")
T_TUNE = ("2024-10-01", "2024-12-31")
HOLDOUT = ("2025-01-01", "2025-12-31")
HALF_LIVES = (10.0, 30.0, 90.0)
POWERS = (1.0, 2.0)
SCOPES = ("cell", "region")
TEMPERATURES = (0.1, 0.2, 0.3, 0.5, 1.0)
REPORTS = REPO / "reports"


def log(msg: str) -> None:
    print(f"{dt.datetime.now():%H:%M:%S} {msg}", flush=True)


def md_table(df: pd.DataFrame, floatfmt: str = ".3f") -> str:
    return df.to_markdown(index=False, floatfmt=floatfmt) if len(df) else "_(no rows)_"


DROPPED: dict[str, dict] = {}
SOURCE_TABLES: dict[str, list[dict]] = {}
LOCK = REPO / "reports" / "phase8" / "FINAL_LOCK.json"


def holdout_board(fcs, b, ref, ref_prob, n_boot, sample, regimes=None):
    """Holdout scoreboard on a common sample; low-coverage forecasts are left out and recorded."""
    kept, dropped = pick_forecasts(fcs, b.obs, HOLDOUT[0], end=HOLDOUT[1], keep={ref, fcs[0].name})
    DROPPED[f"{sample}/{b.region}/{b.variable}"] = dropped
    return scoreboard(
        kept,
        b.obs,
        b.variable,
        b.region,
        ref,
        ref_prob,
        n_boot=n_boot,
        sample=sample,
        window=(pd.Timestamp(HOLDOUT[0]), pd.Timestamp(HOLDOUT[1])),
        regimes=regimes,
    )


def ensemble_fraction(b, land, t):
    """P(>= t) from all members of all ensemble sources pooled (the no-extreme-layer probability)."""
    ms = [f.ens.where(land) for f in b.forecasts if f.ens is not None]
    if not ms:
        return None
    fr = [((m >= t).where(np.isfinite(m))).mean("member") for m in ms]
    return xr.concat(fr, dim="e").mean("e", skipna=True)


def run_one(cfg, root, region, variable, n_boot, do_ablations, sources=None):
    t_start = time.monotonic()
    b = assemble(cfg, root, region, variable, sources=sources)
    if b is None:
        return None
    land = np.isfinite(b.truth).any("time")
    clim = climatology(cfg, root, region, variable)
    static = static_features(cfg, root, region, land.values)
    base, ref_prob = baselines(cfg, root, b)
    kind = "rain" if variable == "precip" else "temp"
    thr = THRESHOLDS[variable]
    tune_m = window_mask(b.like, *TUNE)
    hold_m = window_mask(b.like, *HOLDOUT)
    out = {"region": region, "variable": variable, "coverage": b.coverage, "sources": sources}
    obs = b.obs.where(land)

    # ------------------------------------------------------------------ Phase 3
    from trustcast.bias.decayed import decayed_bias_correction
    from trustcast.bias.qm import rolling_qm

    raw = {f.name: f.det.where(land) for f in b.forecasts}
    eq_raw = equal_mean(raw).assign_coords(valid_day=b.like.valid_day)
    # L1 candidates: pooled quantile mapping; for temperature also per-cell decayed bias removal
    # and both. The best on the tune window is then gated against raw on the holdout.
    qm = {n: rolling_qm(d, obs, kind) for n, d in raw.items()}
    l1_opts = {"qm": (True, False, qm)}
    if kind == "temp":
        cell = {n: decayed_bias_correction(d, obs) for n, d in raw.items()}
        both = {n: decayed_bias_correction(d, obs) for n, d in qm.items()}
        l1_opts |= {"cell_bias": (False, True, cell), "qm+cell_bias": (True, True, both)}
    l1_tune = {
        k: pooled_rmse([equal_mean(v[2]).assign_coords(valid_day=b.like.valid_day)], obs, tune_m)[0]
        for k, v in l1_opts.items()
    }
    l1_name = min(l1_tune, key=l1_tune.get)
    use_qm, use_cell, corrected = l1_opts[l1_name]
    eq_l1 = equal_mean(corrected).assign_coords(valid_day=b.like.valid_day)
    cand = f"equal_mean_{l1_name}"
    sb_l1 = holdout_board(
        [Forecast(cand, "L1", eq_l1), Forecast("equal_mean", "baseline", eq_raw)],
        b,
        "equal_mean",
        ref_prob,
        n_boot,
        "L1",
    )
    v_l1 = verdict(sb_l1, cand, "equal_mean") | {"variant": l1_name, "tune_rmse": l1_tune}
    log(f"{region} {variable} L1 {v_l1}")
    if not v_l1["passes"]:
        use_qm, use_cell = False, False
    dets = corrected if v_l1["passes"] else raw
    eq_prev = eq_l1 if v_l1["passes"] else eq_raw

    grid_rows = []
    dm_cache = {}
    for hl, scope in itertools.product(HALF_LIVES, SCOPES):
        dm_cache[(hl, scope)] = {n: decayed_mse(d, obs, hl, scope) for n, d in dets.items()}
        for p in POWERS:
            ba, _ = blend_a(dets, dm_cache[(hl, scope)], p)
            grid_rows.append(
                {
                    "half_life": hl,
                    "scope": scope,
                    "p": p,
                    "rmse_tune": pooled_rmse([ba], obs, tune_m)[0],
                }
            )
    grid = pd.DataFrame(grid_rows).sort_values("rmse_tune")
    best = grid.iloc[0].to_dict()
    log(f"{region} {variable} A best {best}")
    ba, _ = blend_a(dets, dm_cache[(best["half_life"], best["scope"])], best["p"])
    fa = Forecast("blend_A", "L3A", ba)
    prev_name = cand if v_l1["passes"] else "equal_mean"
    fprev = Forecast(prev_name, "prev", eq_prev)
    sb3 = holdout_board(
        [fa, fprev, *[f for f in base if f.name in ("superensemble", "climatology", "persistence")]]
        + [Forecast(f.name, "source", f.det.where(land), f.ens) for f in b.forecasts],
        b,
        prev_name,
        ref_prob,
        n_boot,
        "phase3",
    )
    v_a = verdict(sb3, "blend_A", prev_name)
    se_rows = overall(sb3)[overall(sb3).forecast == "superensemble"]
    out["phase3"] = {"L1": v_l1, "A_params": best, "A_vs_prev": v_a}
    log(f"{region} {variable} A vs {prev_name}: {v_a}")
    # rule 5: a layer that fails its gate is disabled. p = 0 gives equal weights over the available
    # sources, i.e. the previous layer (equal mean of the L1 output); B then builds on that.
    p_ship = best["p"] if v_a["passes"] else 0.0
    f_ship = fa if v_a["passes"] else fprev

    # ------------------------------------------------------------------ Phase 4
    pc = PipelineConfig(
        qm=use_qm,
        cell_bias=use_cell,
        half_life=best["half_life"],
        p=p_ship,
        scope=best["scope"],
        gate=True,
        tail_map=False,
        extremes=False,
        uncertainty=False,
    )
    res_b = run_pipeline(b, pc, clim, static)
    names, x = stack_sources(res_b.dets)
    avail = np.isfinite(x)
    w_a = res_b.weights_a.transpose("source", *ORDER).values.reshape(len(names), -1)
    t_rows = []
    blends = {}
    for T in TEMPERATURES:
        w = res_b.gate.weights(T, w_a, avail)
        blends[T] = apply_weights(x, w, b.like)
        t_rows.append(
            {
                "temperature": T,
                "rmse_T_tune": pooled_rmse([blends[T]], obs, window_mask(b.like, *T_TUNE))[0],
            }
        )
    tgrid = pd.DataFrame(t_rows).sort_values("rmse_T_tune")
    T_best = float(tgrid.iloc[0]["temperature"])
    fb = Forecast("blend_B", "L3B", blends[T_best])
    sb4 = holdout_board([fb, f_ship], b, f_ship.name, ref_prob, n_boot, "phase4")
    v_b = verdict(sb4, "blend_B", f_ship.name)
    out["phase4"] = {
        "temperature": T_best,
        "B_vs_prev": v_b,
        "B_reference": f_ship.name,
        "regimes": regime_counts(res_b.regimes).to_dict(),
    }
    log(f"{region} {variable} B vs {f_ship.name}: {v_b}")

    # ------------------------------------------------------------------ Phase 5
    full_cfg = pc.but(
        gate=v_b["passes"], temperature=T_best, tail_map=True, extremes=True, uncertainty=True
    )
    full = run_pipeline(b, full_cfg, clim, static)
    layer_prev = fb if v_b["passes"] else f_ship
    # L5a gate: the tail mapping is judged on its purpose, event skill (ETS at the first threshold)
    v_tail = event_verdict(full.final_det, layer_prev.det, obs, thr[0], hold_m, n_boot)
    log(
        f"{region} {variable} L5a tail map vs {layer_prev.name}: "
        f"{ {k: v for k, v in v_tail.items() if k != 'table'} }"
    )
    brier_rows, rel = [], []
    for t in thr:
        ens_p = ensemble_fraction(b, land, t)
        cands = {"classifier": full.probs.get(t)}
        if ens_p is not None:
            cands["ensemble_fraction"] = ens_p
        if ref_prob is not None:
            cands["climatology"] = ref_prob[t].where(land)
        for name, pr in cands.items():
            if pr is None:
                continue
            rel.append(reliability_rows(pr, obs, t, hold_m, name))
        for other in [k for k in cands if k != "classifier"]:
            r, n, rate = brier_compare(cands["classifier"], cands[other], obs, t, hold_m, n_boot)
            brier_rows.append(
                {
                    "threshold": t,
                    "vs": other,
                    "n": n,
                    "event_rate": rate,
                    "brier_classifier": r.score_a,
                    "brier_other": r.score_b,
                    "d_brier": r.diff,
                    "ci_low": r.ci_low,
                    "ci_high": r.ci_high,
                    "significant": r.significant,
                }
            )
    # L5b gate: classifier Brier at the first threshold significantly lower than the strongest
    # alternative (ensemble fraction if an ensemble exists, else climatology), higher than none
    first = [r for r in brier_rows if r["threshold"] == thr[0]]
    main_alt = (
        "ensemble_fraction" if any(r["vs"] == "ensemble_fraction" for r in first) else "climatology"
    )
    v_cls = {
        "vs": main_alt,
        "passes": bool(
            any(r["vs"] == main_alt and r["significant"] and r["d_brier"] < 0 for r in first)
            and not any(r["significant"] and r["d_brier"] > 0 for r in first)
        ),
    }
    log(f"{region} {variable} L5b classifiers: {v_cls}")
    if not (v_tail["passes"] and v_cls["passes"]):
        full_cfg = full_cfg.but(tail_map=v_tail["passes"], extremes=v_cls["passes"])
        full = run_pipeline(b, full_cfg, clim, static)
    out["phase5_gates"] = {"tail_map": v_tail, "classifiers": v_cls}
    ff = Forecast("trustcast", "final", full.final_det)
    sb5 = holdout_board(
        [ff, layer_prev]
        + ([Forecast("equal_mean", "baseline", eq_raw)] if layer_prev.name != "equal_mean" else [])
        + [f for f in base if f.name in ("superensemble", "climatology")],
        b,
        layer_prev.name,
        ref_prob,
        n_boot,
        "phase5",
        regimes=full.regimes,
    )
    ev_rows = overall(sb5)[
        ["forecast", "lead_day", "n_cases", "rmse", "rmse_lo", "rmse_hi"]
        + [c for c in sb5.columns if c.startswith(("ets_", "pod_", "far_", "fbias_", "n_obs_ev_"))]
    ]
    cov = coverage_by_lead(full.lo, full.hi, obs, hold_m)
    dfr = defer_stats(full.final_det, obs, full.defer, hold_m)
    out["phase5"] = {
        "coverage_mean": float(cov["coverage"].mean()),
        "defer": dfr,
        "brier": brier_rows,
    }
    log(f"{region} {variable} coverage {cov.coverage.round(3).tolist()} defer {dfr}")

    ablations = []
    if do_ablations:
        variants = {
            "full": full_cfg,
            "no_AI_sources": full_cfg.but(exclude_sources=AI_SOURCES),
            "no_bias_correction": full_cfg.but(qm=False, cell_bias=False),
            "no_gate (A only)": full_cfg.but(gate=False),
            "no_extreme_layer": full_cfg.but(tail_map=False, extremes=False),
            "no_regime_features": full_cfg.but(regime_features=False),
        }
        for vname, vcfg in variants.items():
            r = (
                full
                if vname == "full"
                else run_pipeline(b, vcfg.but(uncertainty=False), clim, static)
            )
            row = {"variant": vname, "gate_enabled": vcfg.gate}
            fd = r.final_det
            for li in range(fd.sizes["lead_h"]):
                m = hold_m.isel(lead_h=li)
                ok = np.isfinite(fd.isel(lead_h=li)) & np.isfinite(obs.isel(lead_h=li)) & m
                row[f"rmse_d{li + 1}"] = float(
                    np.sqrt(((fd.isel(lead_h=li) - obs.isel(lead_h=li)) ** 2).where(ok).mean())
                )
            t0 = thr[0]
            ok = np.isfinite(fd) & np.isfinite(obs) & hold_m
            f_ev, o_ev = (fd >= t0) & ok, (obs >= t0) & ok
            a = float((f_ev & o_ev).sum())
            fa_ = float((f_ev & ~o_ev).sum())
            c = float((~f_ev & o_ev).sum())
            n = float(ok.sum())
            ar = (a + fa_) * (a + c) / n if n else np.nan
            row[f"ets_{t0}"] = (a - ar) / (a + fa_ + c - ar) if (a + fa_ + c - ar) > 0 else np.nan
            row[f"fbias_{t0}"] = (a + fa_) / (a + c) if (a + c) > 0 else np.nan
            pr = r.probs.get(t0) if r.probs else ensemble_fraction(b, land, t0)
            if pr is not None:
                okp = np.isfinite(pr) & np.isfinite(obs) & hold_m
                row[f"brier_{t0}"] = float(((pr - (obs >= t0)) ** 2).where(okp).mean())
            ablations.append(row)
            log(
                f"{region} {variable} ablation {vname}: {json.dumps({k: round(v, 3) if isinstance(v, float) else v for k, v in row.items()})}"
            )
    out["runtime_s"] = round(time.monotonic() - t_start, 1)
    tables = {
        "grid": grid,
        "sb_l1": sb_l1,
        "sb3": sb3,
        "tgrid": tgrid,
        "sb4": sb4,
        "sb5": sb5,
        "events": ev_rows,
        "brier": pd.DataFrame(brier_rows),
        "reliability": pd.concat(rel) if rel else pd.DataFrame(),
        "coverage": cov,
        "ablations": pd.DataFrame(ablations),
        "se_rows": se_rows,
    }
    return out, tables, full_cfg, full


def write_reports(results):
    for ph in ("phase3", "phase4", "phase5"):
        (REPORTS / ph).mkdir(parents=True, exist_ok=True)
        for old in (REPORTS / ph).glob("*"):
            old.unlink()
    selection = {
        "generated": dt.datetime.now(dt.UTC).isoformat(),
        "protocol": {"tune": TUNE, "temperature_tune": T_TUNE, "holdout": HOLDOUT},
        "models": {},
    }
    md3, md4, md5 = (
        [
            f"# Phase {k} results (development split)",
            "",
            f"> {DISCLAIMER}",
            "",
            f"Tune window {TUNE[0]}..{TUNE[1]}; holdout {HOLDOUT[0]}..{HOLDOUT[1]}; gate rule: "
            "RMSE significantly lower (95 % paired block-bootstrap CI) at >= 3 of 5 lead days and "
            "significantly higher at none. Frozen 2026 test data not read.",
            "",
        ]
        for k in (3, 4, 5)
    )
    for key, (out, tb, full_cfg, _) in results.items():
        region, var = key
        tag = f"{region}_{var}"
        tb["grid"].to_csv(REPORTS / "phase3" / f"tuning_{tag}.csv", index=False)
        pd.concat([tb["sb_l1"], tb["sb3"]]).to_csv(
            REPORTS / "phase3" / f"scoreboard_{tag}.csv", index=False
        )
        tb["tgrid"].to_csv(REPORTS / "phase4" / f"temperature_{tag}.csv", index=False)
        tb["sb4"].to_csv(REPORTS / "phase4" / f"scoreboard_{tag}.csv", index=False)
        for name in ("sb5", "events", "brier", "reliability", "coverage", "ablations"):
            tb[name].to_csv(REPORTS / "phase5" / f"{name}_{tag}.csv", index=False)
        p3 = out["phase3"]
        s3 = overall(tb["sb3"])
        md3 += [
            f"## {region} · {var}",
            "",
            "Data coverage:",
            "",
            md_table(pd.DataFrame(out["coverage"])),
            "",
            f"**L1 bias correction** (equal mean of quantile-mapped sources vs raw): {p3['L1']}",
            "",
            f"**Blender A** tuned: half-life {p3['A_params']['half_life']:.0f} d, p = {p3['A_params']['p']:.0f}, "
            f"scope {p3['A_params']['scope']} (tune RMSE {p3['A_params']['rmse_tune']:.3f}).",
            "",
            f"**A vs previous layer**: {p3['A_vs_prev']}",
            "",
            md_table(
                s3[
                    [
                        "forecast",
                        "lead_day",
                        "n_cases",
                        "rmse",
                        "rmse_lo",
                        "rmse_hi",
                        "d_rmse_vs_ref",
                        "d_rmse_lo",
                        "d_rmse_hi",
                        "crps",
                    ]
                ].sort_values(["lead_day", "rmse"])
            ),
            "",
        ]
        p4 = out["phase4"]
        s4 = overall(tb["sb4"])
        md4 += [
            f"## {region} · {var}",
            "",
            f"Softmax temperature (tuned on {T_TUNE[0]}..{T_TUNE[1]}): {p4['temperature']}",
            "",
            md_table(tb["tgrid"]),
            "",
            f"**B vs {p4['B_reference']}** (previous shipped layer): {p4['B_vs_prev']}",
            "",
            md_table(
                s4[
                    [
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
                ].sort_values(["lead_day", "forecast"])
            ),
            "",
            "Regime counts ((init, lead) cases):",
            "",
            "```",
            json.dumps(p4["regimes"], indent=1),
            "```",
            "",
        ]
        p5 = out["phase5"]
        g5 = out["phase5_gates"]
        md5 += [
            f"## {region} · {var}",
            "",
            "### Events (holdout, all seasons)",
            "",
            md_table(tb["events"]),
            "",
            "### Brier score of event probabilities (paired block bootstrap)",
            "",
            md_table(tb["brier"]),
            "",
            "### Calibrated 90 % intervals (CQR), holdout coverage",
            "",
            md_table(tb["coverage"]),
            "",
            "### L5 gates (event skill, holdout)",
            "",
            f"L5a tail mapping: ETS at {g5['tail_map']['threshold']} vs the previous shipped layer, "
            f"passes = {g5['tail_map']['passes']} (>= 3 leads significantly higher, none lower).",
            "",
            md_table(g5["tail_map"]["table"]),
            "",
            f"L5b classifiers vs {g5['classifiers']['vs']}: passes = {g5['classifiers']['passes']}"
            " (Brier at the first threshold significantly lower, never significantly higher). If"
            " disabled, probabilities are the raw ensemble exceedance fraction.",
            "",
            f"### Defer flag: {p5['defer']}",
            "",
            "### Ablations (holdout)",
            "",
            md_table(tb["ablations"]),
            "",
        ]
        selection["models"][tag] = {
            "qm": full_cfg.qm,
            "cell_bias": full_cfg.cell_bias,
            "half_life": full_cfg.half_life,
            "p": full_cfg.p,
            "scope": full_cfg.scope,
            "gate": full_cfg.gate,
            "temperature": full_cfg.temperature,
            "tail_map": full_cfg.tail_map,
            "extremes": full_cfg.extremes,
            "uncertainty": full_cfg.uncertainty,
            "verdicts": {
                "L1": out["phase3"]["L1"]["passes"],
                "A": out["phase3"]["A_vs_prev"]["passes"],
                "B": out["phase4"]["B_vs_prev"]["passes"],
                "L5a_tail_map": out["phase5_gates"]["tail_map"]["passes"],
                "L5b_classifiers": out["phase5_gates"]["classifiers"]["passes"],
            },
            "sources": list(out["sources"] or []),
            "runtime_s": out["runtime_s"],
        }
    md3 += [
        "",
        "## Source set (frozen with these settings)",
        "",
        f"Eligible: >= {MIN_SOURCE_COVERAGE:.0%} of daily 00Z dev inits (2024-04-01..2025-12-26, from "
        f"the source's own first init) over >= {MIN_SOURCE_DAYS} days. Sources whose dev backfill was "
        "incomplete are left out of every layer and of the frozen test, not partially used.",
        "",
    ]
    for region, rows in SOURCE_TABLES.items():
        md3 += [f"### {region}", "", md_table(pd.DataFrame(rows)), ""]
    md3 += ["", "## Forecasts left out of holdout tables (coverage < 50 % of the best)", ""]
    md3 += [f"- {k}: {v}" for k, v in DROPPED.items() if v] or ["- none"]
    (REPORTS / "phase3" / "PHASE3.md").write_text("\n".join(md3), encoding="utf-8")
    (REPORTS / "phase4" / "PHASE4.md").write_text("\n".join(md4), encoding="utf-8")
    (REPORTS / "phase5" / "PHASE5.md").write_text("\n".join(md5), encoding="utf-8")
    (REPO / "config" / "model_selection.yaml").write_text(
        yaml.safe_dump(selection, sort_keys=False), encoding="utf-8"
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--regions", nargs="+", default=None)
    ap.add_argument("--variables", nargs="+", default=["precip", "tmax"])
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--no-ablations", action="store_true")
    args = ap.parse_args()
    if LOCK.exists():
        # settings are frozen once the final test has run; re-tuning would change what was tested
        log(f"frozen test already run ({LOCK.name}); model selection is frozen, nothing to do")
        return 0
    cfg = load_config()
    root = data_root()
    results = {}
    for region in args.regions or list(cfg.regions):
        SOURCE_TABLES[region] = source_coverage(cfg, root, region)
        sources = sorted({r["source"] for r in SOURCE_TABLES[region] if r["eligible"]})
        log(f"{region} sources: {sources}")
        for var in args.variables:
            r = run_one(cfg, root, region, var, args.n_boot, not args.no_ablations, sources)
            if r is None:
                log(f"{region} {var}: no data")
                continue
            results[(region, var)] = r
    if not results:
        return 1
    write_reports(results)
    log("reports written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
