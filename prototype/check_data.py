"""Sanity-check the collected data before building anything on it.

    python check_data.py

1. Coverage: first usable month and empty gaps per model.
2. Alignment: aggregate hourly lead-1 forecast rain to a day using different window offsets and
   correlate with IMD rain. offset_h is added to each hourly timestamp before taking the calendar
   day, so offset 20 means the day runs 04:00 UTC -> 03:00 UTC (= the 24 h ending 08:30 IST).
"""
import pandas as pd

from config import PREV, TRUTH

OFFSETS = [0, 12, 16, 17, 18, 19, 20, 21, 22, 23]


def load_prev() -> pd.DataFrame:
    files = sorted(PREV.glob("*.parquet"))
    if not files:
        raise SystemExit("No files in data/processed/prev_runs. Run backfill_previous_runs.py first.")
    frames = []
    for f in files:
        d = pd.read_parquet(f)
        d["value"] = pd.to_numeric(d["value"], errors="coerce")
        frames.append(d)
    df = pd.concat(frames, ignore_index=True)
    df["time"] = pd.to_datetime(df["time"])
    return df


def ranges(dates):
    """[d1,d2,d3, d7] -> ['d1..d3', 'd7']"""
    out, dates = [], sorted(dates)
    start = prev = None
    for d in dates:
        if start is None:
            start = prev = d
        elif (d - prev).days == 1:
            prev = d
        else:
            out.append((start, prev)); start = prev = d
    if start is not None:
        out.append((start, prev))
    return [f"{a:%Y-%m-%d}" if a == b else f"{a:%Y-%m-%d}..{b:%Y-%m-%d}" for a, b in out]


def coverage(df: pd.DataFrame):
    print("\n=== Coverage (per model, all variables/leads) ===")
    df = df.assign(month=df["time"].dt.to_period("M"))
    for model, g in df.groupby("model"):
        monthly = g.groupby("month")["value"].apply(lambda s: s.isna().mean())
        ok = monthly[monthly < 0.05]
        first_ok = ok.index[0] if len(ok) else None
        late = g[g["month"] >= "2024-03"]
        print(f"{model}: usable from {first_ok}; empty share since 2024-03 = {late['value'].isna().mean():.2%}")

    print("\n=== Days with >= 6 missing hours (lead 1, rain, since 2024-03) ===")
    f = df[(df["variable"] == "precipitation") & (df["lead_day"] == 1) & (df["time"] >= "2024-03-01")].copy()
    f["date"] = f["time"].dt.normalize()
    f["isna"] = f["value"].isna()
    miss = f.groupby(["model", "date"])["isna"].sum()
    miss = miss[miss >= 6]
    if miss.empty:
        print("none")
    for model in sorted(set(f["model"])):
        days = [d for (m, d) in miss.index if m == model]
        if days:
            print(f"{model}: " + ", ".join(ranges(days)))


def alignment(df: pd.DataFrame):
    truth_file = TRUTH / "imd_points.parquet"
    if not truth_file.exists():
        print("\n(no IMD truth yet: run download_imd_truth.py)")
        return
    t = pd.read_parquet(truth_file)
    t = t[t["variable"] == "rain_mm"].copy()
    t["date"] = pd.to_datetime(t["time"]).dt.normalize()
    t = t.dropna(subset=["value"])
    print(f"\n=== Alignment test: IMD rain covers {t['date'].min():%Y-%m-%d} to {t['date'].max():%Y-%m-%d}, "
          f"{t['point_id'].nunique()} point(s) ===")

    f = df[(df["variable"] == "precipitation") & (df["lead_day"] == 1) & (df["time"] >= "2024-03-01")]
    models = sorted(set(f["model"]))
    pearson, spearman, ndays = {}, {}, {}
    for off in OFFSETS:
        d = f.assign(date=(f["time"] + pd.Timedelta(hours=off)).dt.normalize())
        g = d.groupby(["model", "point_id", "date"])["value"].agg(["sum", "count"]).reset_index()
        g = g[g["count"] == 24]                                # only complete 24 h windows
        m = g.merge(t[["point_id", "date", "value"]], on=["point_id", "date"]).dropna()
        for model in models:
            x = m[m["model"] == model]
            if len(x) > 30:
                pearson[(off, model)] = x["sum"].corr(x["value"])
                spearman[(off, model)] = x["sum"].corr(x["value"], method="spearman")
                ndays[off] = len(x)
    if not pearson:
        print("Not enough overlapping days yet (need IMD rain for the same period as the forecasts).")
        return
    P = pd.Series(pearson).unstack().round(3)
    S = pd.Series(spearman).unstack().round(3)
    print("\nPearson correlation (rows = offset_h):\n", P.to_string())
    print("\nSpearman (rank) correlation:\n", S.to_string())
    print(f"\nBest offset by mean Pearson:  {P.mean(axis=1).idxmax()}h")
    print(f"Best offset by mean Spearman: {S.mean(axis=1).idxmax()}h   (days per model/offset ~ {max(ndays.values())})")
    print("Expected: about 20h. If the curve is flat across 19-22h, the choice matters little.")


if __name__ == "__main__":
    prev = load_prev()
    coverage(prev)
    alignment(prev)
