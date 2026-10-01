"""Helpers for layer gates ("every layer earns its place") and probabilistic comparisons."""

from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

from trustcast.blend.features import ORDER
from trustcast.verify.bootstrap import (
    BootResult,
    aggregate_blocks,
    block_ids,
    paired_block_bootstrap,
)
from trustcast.verify.metrics import reliability_table, scores_from_stats
from trustcast.verify.scoreboard import overall

# Gate rule, fixed before looking at results: the candidate ships if its RMSE is significantly lower
# (95 % CI of the paired difference < 0) at >= MIN_BETTER_LEADS of the 5 lead days and significantly
# higher at none.
MIN_BETTER_LEADS = 3


def window_mask(like: xr.DataArray, start: str | None, end: str | None) -> xr.DataArray:
    """Boolean (init_time, lead_h) mask of valid days within [start, end]."""
    vd = like["valid_day"]
    m = xr.ones_like(vd, dtype=bool)
    if start:
        m = m & (vd >= np.datetime64(start))
    if end:
        m = m & (vd <= np.datetime64(end))
    return m


def pooled_rmse(fcs: list[xr.DataArray], obs: xr.DataArray, mask: xr.DataArray) -> list[float]:
    """RMSE of each forecast over the common valid cases inside ``mask`` (all leads pooled)."""
    common = np.isfinite(obs) & mask
    for f in fcs:
        common = common & np.isfinite(f)
    return [float(np.sqrt(((f - obs) ** 2).where(common).mean())) for f in fcs]


MIN_REL_COVERAGE = 0.5


def pick_forecasts(allf, obs, start, exclude=(), end=None, keep=()):
    """Forecasts with >= 50 % of the best lead-1 coverage in [start, end]; returns (kept, dropped).

    A common-sample table is only as large as its sparsest member, so forecasts with little data in
    the window are left out (and listed) rather than silently shrinking every row. Names in ``keep``
    are kept whenever they have any data (layer candidate and reference).
    """
    days = pd.DatetimeIndex(obs.valid_day.isel(lead_h=0).values)
    inwin = np.asarray(days >= pd.Timestamp(start))
    if end is not None:
        inwin &= np.asarray(days <= pd.Timestamp(end))
    ob_ok = np.isfinite(obs.isel(lead_h=0).values[inwin])
    cov = {}
    for f in allf:
        if f.name in exclude:
            continue
        v = np.isfinite(f.det.isel(lead_h=0).values[inwin]) & ob_ok
        cov[f.name] = v.sum() / max(ob_ok.sum(), 1)
    best = max(cov.values(), default=0)
    kept = [
        f
        for f in allf
        if f.name in cov
        and best > 0
        and (cov[f.name] >= MIN_REL_COVERAGE * best or (f.name in keep and cov[f.name] > 0))
    ]
    dropped = {n: round(float(c), 3) for n, c in cov.items() if n not in {f.name for f in kept}}
    return kept, dropped


def verdict(sb: pd.DataFrame, candidate: str, reference: str) -> dict:
    """Apply the gate rule to scoreboard rows (season 'all') of ``candidate`` vs ``reference``."""
    if sb.empty or "forecast" not in sb:
        return {
            "candidate": candidate,
            "reference": reference,
            "leads_significantly_better": 0,
            "leads_significantly_worse": 0,
            "mean_d_rmse": float("nan"),
            "passes": False,
            "note": "no common cases in the holdout window",
        }
    ov = overall(sb)
    rows = ov[ov.forecast == candidate].sort_values("lead_day")
    better = int((rows["d_rmse_hi"] < 0).sum())
    worse = int((rows["d_rmse_lo"] > 0).sum())
    return {
        "candidate": candidate,
        "reference": reference,
        "leads_significantly_better": better,
        "leads_significantly_worse": worse,
        "mean_d_rmse": float(rows["d_rmse_vs_ref"].mean()),
        "passes": bool(better >= MIN_BETTER_LEADS and worse == 0),
    }


def _flat(da: xr.DataArray) -> np.ndarray:
    return da.transpose(*ORDER).values.ravel()


def _ets(s: dict) -> np.ndarray:
    a, b, c, n = (np.asarray(s[k], dtype=float) for k in ("hit", "fa", "miss", "n"))
    with np.errstate(all="ignore"):
        ar = (a + b) * (a + c) / n
        return (a - ar) / (a + b + c - ar)


def event_verdict(
    cand: xr.DataArray,
    ref: xr.DataArray,
    obs: xr.DataArray,
    t: float,
    mask: xr.DataArray,
    n_boot: int = 1000,
) -> dict:
    """Event gate for the extreme layer (its purpose is event skill, not RMSE): ETS(cand) - ETS(ref)
    at threshold ``t`` per lead day, paired block bootstrap on common cases. Ships if ETS is
    significantly higher at >= MIN_BETTER_LEADS leads and significantly lower at none."""
    rows = []
    for li in range(cand.sizes["lead_h"]):
        sel = {"lead_h": li}
        a, r, o = (
            x.isel(sel).transpose("init_time", "lat", "lon").values.ravel()
            for x in (cand, ref, obs)
        )
        m = np.broadcast_to(
            mask.isel(sel).values[:, None, None],
            cand.isel(sel).transpose("init_time", "lat", "lon").shape,
        ).ravel()
        ok = np.isfinite(a) & np.isfinite(r) & np.isfinite(o) & m
        days = np.broadcast_to(
            cand.isel(sel)["valid_day"].values[:, None, None],
            cand.isel(sel).transpose("init_time", "lat", "lon").shape,
        ).ravel()[ok]
        ev = o[ok] >= t
        ids = block_ids(days)

        def stats(f, ev=ev, ids=ids, ok=ok):
            fe = f[ok] >= t
            return aggregate_blocks(
                ids,
                {
                    "hit": (fe & ev).astype(float),
                    "fa": (fe & ~ev).astype(float),
                    "miss": (~fe & ev).astype(float),
                    "n": np.ones(ev.size),
                },
            )[1]

        res = paired_block_bootstrap(stats(a), stats(r), _ets, n_boot)
        rows.append(
            {
                "lead_day": li + 1,
                "n_events": int(ev.sum()),
                "ets_cand": res.score_a,
                "ets_ref": res.score_b,
                "d_ets": res.diff,
                "ci_low": res.ci_low,
                "ci_high": res.ci_high,
            }
        )
    df = pd.DataFrame(rows)
    better = int((df.ci_low > 0).sum())
    worse = int((df.ci_high < 0).sum())
    return {
        "threshold": t,
        "leads_significantly_better": better,
        "leads_significantly_worse": worse,
        "mean_d_ets": float(df.d_ets.mean()),
        "passes": bool(better >= MIN_BETTER_LEADS and worse == 0),
        "table": df,
    }


def brier_compare(
    p_a: xr.DataArray,
    p_b: xr.DataArray,
    obs: xr.DataArray,
    t: float,
    mask: xr.DataArray,
    n_boot: int = 1000,
) -> tuple[BootResult, int, float]:
    """Paired block bootstrap of Brier(A) - Brier(B) for event obs >= t on common cases.

    Returns (result, n_cases, observed event rate).
    """
    a, bb, o = _flat(p_a), _flat(p_b), _flat(obs)
    m = np.broadcast_to(
        mask.transpose("init_time", "lead_h").values[:, :, None, None], p_a.transpose(*ORDER).shape
    ).ravel()
    ok = np.isfinite(a) & np.isfinite(bb) & np.isfinite(o) & m
    ev = (o >= t).astype(float)
    days = np.broadcast_to(
        p_a.transpose(*ORDER)["valid_day"].values[:, :, None, None], p_a.transpose(*ORDER).shape
    ).ravel()
    ids = block_ids(days[ok])

    def stats(p):
        return aggregate_blocks(
            ids,
            {
                "nb": np.ones(ok.sum()),
                "sum_bs": (p[ok] - ev[ok]) ** 2,
                "sum_bs_ref": (p[ok] - ev[ok]) ** 2,
            },
        )[1]

    r = paired_block_bootstrap(stats(a), stats(bb), lambda s: scores_from_stats(s)["brier"], n_boot)
    return r, int(ok.sum()), float(ev[ok].mean()) if ok.any() else float("nan")


def reliability_rows(
    prob: xr.DataArray, obs: xr.DataArray, t: float, mask: xr.DataArray, name: str
) -> pd.DataFrame:
    """Reliability-diagram rows for probabilities ``prob`` of obs >= t."""
    p, o = _flat(prob), _flat(obs)
    m = np.broadcast_to(
        mask.transpose("init_time", "lead_h").values[:, :, None, None], prob.transpose(*ORDER).shape
    ).ravel()
    ok = np.isfinite(p) & np.isfinite(o) & m
    return pd.DataFrame(
        [
            {"forecast": name, "threshold": t, **r}
            for r in reliability_table(p[ok], o[ok] >= t, bins=10)
        ]
    )


def coverage_by_lead(
    lo: xr.DataArray, hi: xr.DataArray, obs: xr.DataArray, mask: xr.DataArray
) -> pd.DataFrame:
    """Empirical coverage of [lo, hi] per lead day."""
    rows = []
    for li in range(lo.sizes["lead_h"]):
        sl = {"lead_h": li}
        ok = np.isfinite(lo.isel(sl)) & np.isfinite(obs.isel(sl)) & mask.isel(sl)
        inside = (obs.isel(sl) >= lo.isel(sl)) & (obs.isel(sl) <= hi.isel(sl))
        n = int(ok.sum())
        rows.append(
            {
                "lead_day": li + 1,
                "n": n,
                "coverage": float(inside.where(ok).sum() / n) if n else float("nan"),
                "mean_width": float((hi.isel(sl) - lo.isel(sl)).where(ok).mean()),
            }
        )
    return pd.DataFrame(rows)


def defer_stats(
    final: xr.DataArray, obs: xr.DataArray, defer: xr.DataArray, mask: xr.DataArray
) -> dict:
    """RMSE of flagged vs unflagged cases (a useful flag has flagged RMSE > unflagged)."""
    ok = np.isfinite(final) & np.isfinite(obs) & mask
    se = (final - obs) ** 2
    flagged = ok & defer
    unflag = ok & ~defer
    nf, nu = int(flagged.sum()), int(unflag.sum())
    rf = float(np.sqrt(se.where(flagged).mean())) if nf else float("nan")
    ru = float(np.sqrt(se.where(unflag).mean())) if nu else float("nan")
    return {
        "flag_rate": nf / max(nf + nu, 1),
        "rmse_flagged": rf,
        "rmse_unflagged": ru,
        "ratio": rf / ru if nu and nf else float("nan"),
        "n_flagged": nf,
    }
