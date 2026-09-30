"""One command: regenerate every Phase 2 table and figure from the canonical + truth stores.

    python scripts/run_verification.py                  # dev period, all regions, 1000 bootstraps
    python scripts/run_verification.py --n-boot 200     # quicker

Outputs (committed, small):  reports/phase2/
    scoreboard_full.csv   every forecast x region x variable x lead x season, 95 % CIs, paired diffs
    reliability.csv       ensemble reliability data (64.5 mm, lead days 1 and 3)
    coverage.csv          which data each forecast actually had
    SCOREBOARD.md         summary tables
    fig_*.png             figures
Outputs (data, git-ignored): data/skill/<region>/<variable>/<forecast>.parquet (skill table)

Never reads the frozen test period (valid days >= 2026-01-01).
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trustcast import DISCLAIMER
from trustcast.blend.baselines import (
    build_climatology,
    clim_for,
    equal_mean,
    persistence,
    superensemble,
)
from trustcast.config import data_root, load_config
from trustcast.verify.data import VAR_PAIRS, load_canonical, load_truth, obs_like
from trustcast.verify.scoreboard import (
    THRESHOLDS,
    Forecast,
    reliability,
    scoreboard,
    write_skill_table,
)

REFERENCE = "equal_mean"
# Scoring samples: every row of a sample is scored on the same cases (common sample).
# main: from when the IFS/AIFS dynamical archives start; AIFS-ENS (from 2025-07-02) is excluded.
# late: the AIFS-ENS era, all forecasts.
SAMPLES = {
    "main": {"start": pd.Timestamp("2024-04-01"), "exclude": {"ecmwf_aifs_ens"}},
    "late": {"start": pd.Timestamp("2025-07-02"), "exclude": set()},
}
MIN_REL_COVERAGE = 0.5


def pick_forecasts(allf, obs, start, exclude):
    """Forecasts with >= 50 % of the best lead-1 coverage in the window; returns (kept, dropped)."""
    days = pd.DatetimeIndex(obs.valid_day.isel(lead_h=0).values)
    inwin = np.asarray(days >= start)
    ob_ok = np.isfinite(obs.isel(lead_h=0).values[inwin])
    cov = {}
    for f in allf:
        if f.name in exclude:
            continue
        v = np.isfinite(f.det.isel(lead_h=0).values[inwin]) & ob_ok
        cov[f.name] = v.sum() / max(ob_ok.sum(), 1)
    best = max(cov.values(), default=0)
    kept = [
        f for f in allf if f.name in cov and cov[f.name] >= MIN_REL_COVERAGE * best and best > 0
    ]
    dropped = {n: round(float(c), 3) for n, c in cov.items() if n not in {f.name for f in kept}}
    return kept, dropped


OUT = REPO / "reports" / "phase2"


def _valid_day(inits: pd.DatetimeIndex, lead_h: np.ndarray) -> np.ndarray:
    return (
        inits.values[:, None] + (lead_h.astype("timedelta64[h]") - np.timedelta64(3, "h"))[None, :]
    )


def assemble(cfg, root, region: str, variable: str):
    """Sources on a common init axis + truth arranged like them."""
    fc_var, truth_var = VAR_PAIRS[variable]
    raw = {}
    for name, a in cfg.adapters.items():
        if a.use != "eval" or a.type == "ncum" or not a.enabled:
            continue
        ds = load_canonical(root, name, region)
        if ds is not None and ds.sizes["init_time"]:
            raw[a.source] = ds[fc_var]
    if not raw:
        return None, None, None
    inits = pd.DatetimeIndex(
        sorted(set().union(*[set(pd.DatetimeIndex(d.init_time.values)) for d in raw.values()]))
    )
    lead_h = next(iter(raw.values())).lead_h.values
    vd = _valid_day(inits, lead_h)
    coverage, forecasts = [], []
    for src, da in raw.items():
        da = (
            da.reindex(init_time=inits)
            .assign_coords(valid_day=(("init_time", "lead_h"), vd))
            .load()
        )
        ens = da if "member" in da.dims else None
        det = da.mean("member") if ens is not None else da
        forecasts.append(Forecast(src, "source", det, ens))
        have = pd.DatetimeIndex(da.init_time.values)[np.isfinite(det.values).any(axis=(1, 2, 3))]
        coverage.append(
            {
                "region": region,
                "variable": variable,
                "forecast": src,
                "first_init": have.min() if len(have) else None,
                "last_init": have.max() if len(have) else None,
                "n_inits": len(have),
                "members": int(da.sizes.get("member", 1)),
            }
        )
    truth = load_truth(root, region)[truth_var]
    grid = forecasts[0].det
    obs = obs_like(grid.to_dataset(name="x"), truth.sel(lat=grid.lat, lon=grid.lon)).assign_coords(
        valid_day=(("init_time", "lead_h"), vd)
    )
    return forecasts, obs, (truth, coverage)


def add_baselines(cfg, root, region, variable, forecasts, obs, truth):
    dets = {f.name: f.det for f in forecasts}
    like = forecasts[0].det
    out = [
        Forecast("equal_mean", "baseline", equal_mean(dets).assign_coords(valid_day=like.valid_day))
    ]
    out.append(Forecast("superensemble", "baseline", superensemble(dets, obs)))
    out.append(
        Forecast(
            "persistence",
            "baseline",
            persistence(truth.sel(lat=like.lat, lon=like.lon), like).assign_coords(
                valid_day=like.valid_day
            ),
        )
    )
    clim_var = "rain" if variable == "precip" else "tmax"
    clim = build_climatology(root, clim_var, cfg.regions[region], THRESHOLDS[variable])
    ref_prob = None
    if clim is not None:
        out.append(
            Forecast(
                "climatology",
                "baseline",
                clim_for(clim, "mean", like).assign_coords(valid_day=like.valid_day),
            )
        )
        ref_prob = {t: clim_for(clim, f"p_ge_{t}", like) for t in THRESHOLDS[variable]}
    return out, ref_prob, clim is not None


def fig_by_lead(sb: pd.DataFrame, metric: str, path: Path, title: str) -> None:
    d = sb[sb.season == "all"]
    fig, ax = plt.subplots(figsize=(8, 4.8))
    for name, g in d.groupby("forecast"):
        g = g.sort_values("lead_day")
        style = "--" if g.kind.iloc[0] == "baseline" else "-"
        yerr = None
        if f"{metric}_lo" in g:
            yerr = np.vstack([g[metric] - g[f"{metric}_lo"], g[f"{metric}_hi"] - g[metric]])
            yerr = np.where(np.isfinite(yerr), yerr, 0)
        ax.errorbar(
            g.lead_day + 0.03 * (hash(name) % 7 - 3),
            g[metric],
            yerr=yerr,
            ls=style,
            marker="o",
            ms=3,
            capsize=2,
            label=name,
        )
    ax.set_xlabel("lead day (IMD day windows)")
    ax.set_ylabel(metric)
    ax.set_title(title, fontsize=10)
    ax.legend(fontsize=7, ncol=2)
    ax.grid(alpha=0.3)
    fig.text(0.01, 0.01, DISCLAIMER, fontsize=6, alpha=0.7)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def fig_reliability(rel: pd.DataFrame, path: Path, title: str) -> None:
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], "k:", lw=1)
    for name, g in rel.groupby("forecast"):
        g = g[g.n >= 20]
        ax.plot(g.mean_prob, g.obs_freq, marker="o", label=f"{name}")
    ax.set_xlabel("forecast probability")
    ax.set_ylabel("observed frequency")
    ax.set_title(title, fontsize=9)
    ax.legend(fontsize=7)
    fig.text(0.01, 0.01, DISCLAIMER, fontsize=6, alpha=0.7)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def fmt(v, lo=None, hi=None, nd=2):
    if v is None or not np.isfinite(v):
        return "n/a"
    s = f"{v:.{nd}f}"
    if lo is not None and np.isfinite(lo) and np.isfinite(hi):
        s += f" [{lo:.{nd}f}, {hi:.{nd}f}]"
    return s


def summary_md(
    sb: pd.DataFrame, cov: pd.DataFrame, rel_files: list[str], clim_ok: dict, excluded: dict
) -> str:
    lines = [
        "# Phase 2 baseline scoreboard (development period)",
        "",
        f"Generated {dt.datetime.now(dt.UTC):%Y-%m-%d %H:%M} UTC by `python scripts/run_verification.py`.",
        "",
        f"> {DISCLAIMER}",
        "",
        "All scores pooled over IMD land cells and 00Z inits; 95 % intervals from a paired block bootstrap",
        "(5-day blocks). `Δ vs equal_mean` < 0 means lower error than the equal-weight mean;",
        "**bold** = the 95 % interval excludes 0. Frozen 2026 test data were not read.",
        "",
        "Samples: **main** = valid days from 2024-04-01, all forecasts except AIFS-ENS; **late** =",
        "valid days from 2025-07-02 (AIFS-ENS era), all forecasts. Within a sample and lead, every",
        "row is scored on the same cases (all listed forecasts and the observation valid).",
        "",
        "## Data coverage",
        "",
        cov.to_markdown(index=False),
        "",
        "Forecasts left out of a sample (coverage below 50 % of the best, shown as fraction):",
        "",
        *[f"- {k}: {v}" for k, v in excluded.items() if v],
        "",
    ]
    for (sample, region, var), g in sb.groupby(["sample", "region", "variable"]):
        g = g[g.season == "all"]
        unit = "mm/day" if var == "precip" else "°C"
        lines += [
            f"## [{sample}] {region} · {var} ({unit}) · all seasons",
            "",
            "| forecast | lead | n | RMSE [95 % CI] | Δ RMSE vs equal_mean [CI] | CRPS [CI] | bias |",
            "|---|---|---|---|---|---|---|",
        ]
        for _, r in g.sort_values(["lead_day", "forecast"]).iterrows():
            d = fmt(r.get("d_rmse_vs_ref"), r.get("d_rmse_lo"), r.get("d_rmse_hi"))
            if np.isfinite(r.get("d_rmse_lo", np.nan)) and (
                r["d_rmse_lo"] > 0 or r["d_rmse_hi"] < 0
            ):
                d = f"**{d}**"
            lines.append(
                f"| {r.forecast} | {r.lead_day} | {r.n_cases:,} | {fmt(r.rmse, r.rmse_lo, r.rmse_hi)} | "
                f"{d} | {fmt(r.crps, r.crps_lo, r.crps_hi)} | {fmt(r.bias)} |"
            )
        lines.append("")
        for t in THRESHOLDS[var]:
            lines += [
                f"### Events ≥ {t} {'mm' if var == 'precip' else '°C'} · all seasons",
                "",
                "| forecast | lead | obs events | ETS [95 % CI] | POD | FAR | freq. bias | BSS vs clim [CI] |",
                "|---|---|---|---|---|---|---|---|",
            ]
            for _, r in g.sort_values(["lead_day", "forecast"]).iterrows():
                bss = (
                    fmt(r.get(f"bss_{t}"), r.get(f"bss_{t}_lo"), r.get(f"bss_{t}_hi"))
                    if f"bss_{t}" in r
                    else "n/a (no clim.)"
                )
                lines.append(
                    f"| {r.forecast} | {r.lead_day} | {int(r[f'n_obs_ev_{t}'])} | "
                    f"{fmt(r[f'ets_{t}'], r[f'ets_{t}_lo'], r[f'ets_{t}_hi'], 3)} | {fmt(r[f'pod_{t}'])} | "
                    f"{fmt(r[f'far_{t}'])} | {fmt(r[f'fbias_{t}'])} | {bss} |"
                )
            lines.append("")
    lines += ["## Figures", ""] + [f"![{p}]({p})" for p in sorted(rel_files)]
    lines += [
        "",
        "## Notes",
        "",
        f"- Climatology baseline available: {clim_ok}. Without the 1991-2020 IMD normal on disk the",
        "  climatology row and Brier skill scores are omitted rather than approximated.",
        "- Previous Runs sources (ecmwf_ifs HRES, dwd_icon, cmc_gem) are ~11.5 h staler than true-init",
        "  sources at the same lead (DATA_SOURCES.md).",
        "- Ensemble CRPS is the fair CRPS; deterministic CRPS equals MAE.",
        "- Season strata and full per-stratum results: `scoreboard_full.csv`.",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--regions", nargs="+", default=None)
    ap.add_argument("--no-skill-table", action="store_true")
    args = ap.parse_args()
    cfg = load_config()
    root = data_root()
    OUT.mkdir(parents=True, exist_ok=True)
    for old in [*OUT.glob("fig_*.png"), *OUT.glob("*.csv"), *OUT.glob("*.md")]:
        old.unlink()  # never leave outputs of an earlier run behind
    boards, rels, covs, figs, clim_ok, excluded = [], [], [], [], {}, {}
    for region in args.regions or list(cfg.regions):
        for variable in ("precip", "tmax"):
            forecasts, obs, extra = assemble(cfg, root, region, variable)
            if forecasts is None:
                print(f"{region} {variable}: no canonical data yet")
                continue
            truth, coverage = extra
            covs += coverage
            baselines, ref_prob, has_clim = add_baselines(
                cfg, root, region, variable, forecasts, obs, truth
            )
            clim_ok[f"{region}/{variable}"] = has_clim
            allf = forecasts + baselines
            sb = None
            for sname, spec in SAMPLES.items():
                kept, dropped = pick_forecasts(allf, obs, spec["start"], spec["exclude"])
                excluded[f"{sname}/{region}/{variable}"] = dropped
                if REFERENCE not in {f.name for f in kept} or len(kept) < 2:
                    print(f"{region} {variable} {sname}: not enough data yet", flush=True)
                    continue
                s = scoreboard(
                    kept,
                    obs,
                    variable,
                    region,
                    REFERENCE,
                    ref_prob,
                    n_boot=args.n_boot,
                    sample=sname,
                    window=(spec["start"], None),
                )
                boards.append(s)
                print(
                    f"{region} {variable} {sname}: {len(kept)} forecasts, {len(s)} rows, "
                    f"dropped {dropped}",
                    flush=True,
                )
                if sname == "main":
                    sb = s
            if sb is None or sb.empty:
                continue
            unit = "mm/day" if variable == "precip" else "°C"
            for metric in ("rmse", "crps"):
                p = OUT / f"fig_{metric}_by_lead_{region}_{variable}.png"
                fig_by_lead(
                    sb,
                    metric,
                    p,
                    f"{metric.upper()} ({unit}) by lead · {region} · {variable} · dev period",
                )
                figs.append(p.name)
            t0 = THRESHOLDS[variable][0]
            p = OUT / f"fig_ets_{t0}_by_lead_{region}_{variable}.png"
            fig_by_lead(sb, f"ets_{t0}", p, f"ETS ≥ {t0} · {region} · {variable} · dev period")
            figs.append(p.name)
            if variable == "precip":
                for li in (0, 2):
                    rel = reliability(allf, obs, 64.5, li)
                    rel.insert(0, "region", region)
                    rels.append(rel)
                    if len(rel):
                        p = OUT / f"fig_reliability_64.5_lead{li + 1}_{region}.png"
                        fig_reliability(
                            rel, p, f"Reliability P(rain ≥ 64.5 mm) · lead day {li + 1} · {region}"
                        )
                        figs.append(p.name)
            if not args.no_skill_table:
                write_skill_table(allf, obs, variable, region, root / "skill")
    if not boards:
        print("nothing to verify yet")
        return 1
    sb = pd.concat(boards, ignore_index=True)
    sb.to_csv(OUT / "scoreboard_full.csv", index=False, float_format="%.5g")
    rel = pd.concat(rels, ignore_index=True) if rels else pd.DataFrame()
    rel.to_csv(OUT / "reliability.csv", index=False, float_format="%.5g")
    cov = pd.DataFrame(covs)
    cov.to_csv(OUT / "coverage.csv", index=False)
    (OUT / "SCOREBOARD.md").write_text(
        summary_md(sb, cov, figs, clim_ok, excluded), encoding="utf-8"
    )
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
