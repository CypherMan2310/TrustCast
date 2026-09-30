import datetime as dt
from pathlib import Path

import pandas as pd
import requests

URL = "https://api.open-meteo.com/v1/forecast"
POINTS = [(10.0, 76.3), (11.5, 77.0)]          # (lat, lon) - replace with your district centroids
MODELS = ["ecmwf_ifs025", "gfs_seamless", "icon_seamless", "gem_seamless"]
VARS = ["precipitation", "temperature_2m"]
OUT = Path("data/raw")


def split_col(col):
    """'precipitation_gfs_seamless' -> ('precipitation', 'gfs_seamless')"""
    for v in VARS:
        if col == v:
            return v, "default"
        if col.startswith(v + "_"):
            return v, col[len(v) + 1:]
    return col, "unknown"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    fetched = dt.datetime.now(dt.timezone.utc)

    r = requests.get(URL, timeout=60, params={
        "latitude": ",".join(str(p[0]) for p in POINTS),
        "longitude": ",".join(str(p[1]) for p in POINTS),
        "hourly": ",".join(VARS),
        "models": ",".join(MODELS),
        "forecast_days": 7,
        "timezone": "UTC",
    })
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict):        # a single point comes back as a dict
        data = [data]

    frames = []
    for i, loc in enumerate(data):
        long = pd.DataFrame(loc["hourly"]).melt(
            id_vars="time", var_name="col", value_name="value")
        long[["variable", "model"]] = long["col"].apply(lambda c: pd.Series(split_col(c)))
        long["point_id"] = i
        long["req_lat"], long["req_lon"] = POINTS[i]
        long["grid_lat"], long["grid_lon"] = loc["latitude"], loc["longitude"]
        frames.append(long.drop(columns="col"))

    df = pd.concat(frames, ignore_index=True)
    df["fetched_at"] = fetched
    path = OUT / f"om_{fetched:%Y%m%dT%H}.parquet"
    df.to_parquet(path, index=False)
    print(f"saved {len(df)} rows -> {path}")


if __name__ == "__main__":
    main()