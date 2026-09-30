"""Backfill lead-time-stratified past forecasts from the Open-Meteo Previous Runs API.

Resumable: finished model-months are skipped, raw responses are cached.

    python backfill_previous_runs.py --test          # one model, one month: smoke test
    python backfill_previous_runs.py                 # everything from 2024-01-01 to today
    python backfill_previous_runs.py --models gfs_seamless --start 2025-01-01
"""
import argparse
import hashlib
import json
import re
import time

import pandas as pd
import requests

from config import CACHE, DEFAULT_START, LEADS, MODELS, PREV, VARS, load_points

URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
BATCH = 20            # points per request
PAUSE_S = 1.0         # politeness delay between calls
COL_RE = re.compile(r"^(?P<var>[a-z0-9_]+?)_previous_day(?P<lead>\d+)(?:_(?P<model>.+))?$")


def month_chunks(start: pd.Timestamp, end: pd.Timestamp):
    cur = start
    while cur <= end:
        stop = min(cur + pd.offsets.MonthEnd(0), end)
        yield cur, stop
        cur = stop + pd.Timedelta(days=1)


def fetch(params: dict) -> list:
    """GET with on-disk cache, retry on 429/5xx. Returns a list of per-location dicts."""
    key = hashlib.md5(json.dumps(params, sort_keys=True).encode()).hexdigest()
    cache_file = CACHE / f"{key}.json"
    if cache_file.exists():
        data = json.loads(cache_file.read_text())
    else:
        for attempt in range(5):
            r = requests.get(URL, params=params, timeout=120)
            if r.status_code == 429 or r.status_code >= 500:
                wait = 60 * (attempt + 1)
                print(f"   HTTP {r.status_code}, waiting {wait}s (attempt {attempt + 1}/5)")
                time.sleep(wait)
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
            data = r.json()
            break
        else:
            raise RuntimeError("gave up after repeated 429/5xx")
        cache_file.write_text(json.dumps(data))
        time.sleep(PAUSE_S)
    return data if isinstance(data, list) else [data]


def tidy(locs: list, points: pd.DataFrame, model: str) -> pd.DataFrame:
    frames = []
    for loc, (_, p) in zip(locs, points.iterrows()):
        wide = pd.DataFrame(loc["hourly"])
        long = wide.melt(id_vars="time", var_name="col", value_name="value")
        long["value"] = pd.to_numeric(long["value"], errors="coerce")   # None -> NaN (avoids object dtype)
        parsed = long["col"].str.extract(COL_RE)
        long["variable"] = parsed["var"]
        long["lead_day"] = parsed["lead"].astype("Int64")
        long["model"] = parsed["model"].fillna(model)
        long["point_id"] = int(p["id"])
        long["grid_lat"], long["grid_lon"] = loc.get("latitude"), loc.get("longitude")
        frames.append(long.drop(columns="col"))
    return pd.concat(frames, ignore_index=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=str((pd.Timestamp.utcnow() - pd.Timedelta(days=2)).date()))
    ap.add_argument("--models", nargs="+", default=MODELS)
    ap.add_argument("--test", action="store_true", help="one model, one month, then print a summary")
    args = ap.parse_args()

    CACHE.mkdir(parents=True, exist_ok=True)
    PREV.mkdir(parents=True, exist_ok=True)
    points = load_points()
    sig = hashlib.md5(points[["id", "lat", "lon"]].to_csv(index=False).encode()).hexdigest()
    sigfile = PREV / "_points.md5"
    if sigfile.exists() and sigfile.read_text().strip() != sig:
        raise SystemExit(
            "points.csv changed since the existing backfill files were written.\n"
            "Delete the folder data/processed/prev_runs (the download cache can stay) and re-run."
        )
    sigfile.write_text(sig)
    hourly = [f"{v}_previous_day{n}" for v in VARS for n in LEADS]
    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
    models = args.models[:1] if args.test else args.models
    chunks = list(month_chunks(start, end))
    if args.test:
        chunks = chunks[:1]

    for model in models:
        for c0, c1 in chunks:
            out = PREV / f"{model}_{c0:%Y%m}.parquet"
            if out.exists():
                continue
            frames = []
            for i in range(0, len(points), BATCH):
                sub = points.iloc[i:i + BATCH]
                params = {
                    "latitude": ",".join(map(str, sub["lat"])),
                    "longitude": ",".join(map(str, sub["lon"])),
                    "hourly": ",".join(hourly),
                    "models": model,
                    "start_date": f"{c0:%Y-%m-%d}",
                    "end_date": f"{c1:%Y-%m-%d}",
                    "timezone": "UTC",
                }
                try:
                    frames.append(tidy(fetch(params), sub, model))
                except Exception as e:  # keep going; log and move on
                    print(f"!! {model} {c0:%Y-%m}: {e}")
                    with open(CACHE.parent / "failures.log", "a") as f:
                        f.write(f"{model}\t{c0:%Y-%m}\t{e}\n")
                    frames = []
                    break
            if frames:
                df = pd.concat(frames, ignore_index=True)
                df.to_parquet(out, index=False)
                nan = df["value"].isna().mean()
                print(f"ok {model} {c0:%Y-%m}: {len(df):,} rows, {nan:.0%} empty -> {out.name}")
                if args.test:
                    print(df.groupby(["variable", "lead_day"])["value"].agg(["count", "mean"]))
                    print(df.head())


if __name__ == "__main__":
    main()
