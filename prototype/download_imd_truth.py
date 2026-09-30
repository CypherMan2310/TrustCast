"""Download IMD gridded rainfall (0.25 deg) and Tmax (1.0 deg) and extract them at your points.

    python download_imd_truth.py                       # 2024 to current year
    python download_imd_truth.py --start-year 2023

Output: data/truth/imd_points.parquet  (time, point_id, variable, value, grid_lat, grid_lon)

Robustness added after the first real run:
  * past-year files that already exist are not downloaded again
  * downloads are retried (imdpune.gov.in times out often; Ctrl+C and re-run if it hangs)
  * IMD's current-year file is partial, and imdlib refuses partial files. We read the raw
    .grd ourselves, but ONLY after proving our reader reproduces imdlib on a full year.
  * missing-value codes are masked correctly (rain -999, tmax 99.9)
"""
import argparse
import datetime as dt
import shutil
import time

import imdlib as imd
import numpy as np
import pandas as pd
import xarray as xr

from config import TRUTH, load_points

STAGING = TRUTH / "_staging"     # downloads land here first, so a failed retry can never clobber a good file

# grids are fixed by IMD: lat/lon start, step, and size (lon varies fastest, lat ascending)
SPEC = {
    "rain": dict(out="rain_mm", nlat=129, nlon=135, lat0=6.5, lon0=66.5, step=0.25),
    "tmax": dict(out="tmax_c", nlat=31, nlon=31, lat0=7.5, lon0=67.5, step=1.0),
}


def clean(da: xr.DataArray, var: str) -> xr.DataArray:
    da = da.where(da > -100)                # rain missing = -999
    if var == "tmax":
        da = da.where(da < 60)              # tmax missing = 99.9
    return da


def find_grd(base, var: str, year: int):
    """Locate <base>/**/<var>/<year>.grd, ignoring the staging folder and empty files."""
    hits = [h for h in base.rglob(f"{year}.grd")
            if h.parent.name == var and "_staging" not in h.relative_to(base).parts
            and h.stat().st_size > 0]
    return hits[0] if hits else None


def grd_path(var: str, year: int):
    return find_grd(TRUTH, var, year)


def ensure_download(var: str, year: int, tries: int = 3) -> bool:
    """Download into STAGING, then replace the real file only if the new one is non-empty
    and at least as large as what we already have (IMD's current-year file only grows)."""
    have = grd_path(var, year)
    if have is not None and year < dt.date.today().year:
        return True                          # completed past year already on disk
    for i in range(tries):
        try:
            imd.get_data(var, year, year, fn_format="yearwise", file_dir=str(STAGING))
        except Exception as e:               # imdlib may raise AFTER writing the file; check below
            print(f"   download {var} {year}: {type(e).__name__} (attempt {i + 1}/{tries})")
        staged = find_grd(STAGING, var, year) if STAGING.exists() else None
        if staged is not None:
            dest = TRUTH / var / f"{year}.grd"
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists() or dest.stat().st_size <= staged.stat().st_size:
                shutil.copy2(staged, dest)
            staged.unlink()
            return True
        time.sleep(10 * (i + 1))
    print(f"   {var} {year}: server gave no usable file; keeping any previous copy")
    return grd_path(var, year) is not None


def read_grd(path, var: str, year: int) -> xr.DataArray:
    """Read a raw IMD .grd file, including partial years."""
    s = SPEC[var]
    cell = s["nlat"] * s["nlon"]
    raw = np.fromfile(path, dtype="<f4")
    n = raw.size // cell
    if n == 0:
        raise ValueError(f"{path} is empty")
    arr = raw[: n * cell].reshape(n, s["nlat"], s["nlon"])
    return xr.DataArray(
        arr, dims=("time", "lat", "lon"), name=var,
        coords=dict(
            time=pd.date_range(f"{year}-01-01", periods=n),
            lat=s["lat0"] + s["step"] * np.arange(s["nlat"]),
            lon=s["lon0"] + s["step"] * np.arange(s["nlon"]),
        ),
    )


def reader_matches(var: str, year: int, ref: xr.DataArray, points: pd.DataFrame) -> bool:
    """Prove read_grd() reproduces imdlib on a full year, at every point."""
    mine = clean(read_grd(grd_path(var, year), var, year), var)
    for p in points.itertuples():
        a = ref.sel(lat=p.lat, lon=p.lon, method="nearest").values
        b = mine.sel(lat=p.lat, lon=p.lon, method="nearest").values
        if a.shape != b.shape or not np.allclose(a, b, equal_nan=True, atol=1e-3):
            return False
    return True


def extract(da: xr.DataArray, var: str, points: pd.DataFrame) -> list:
    out = []
    for p in points.itertuples():
        s = da.sel(lat=p.lat, lon=p.lon, method="nearest")
        df = s.to_series().rename("value").reset_index()
        df["point_id"] = int(p.id)
        df["variable"] = SPEC[var]["out"]
        df["grid_lat"], df["grid_lon"] = float(s["lat"]), float(s["lon"])
        out.append(df)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-year", type=int, default=2024)
    ap.add_argument("--end-year", type=int, default=dt.date.today().year)
    args = ap.parse_args()

    TRUTH.mkdir(parents=True, exist_ok=True)
    points = load_points()
    rows = []

    for var in SPEC:
        trusted_reader = False               # becomes True once verified against imdlib
        for year in range(args.start_year, args.end_year + 1):
            if not ensure_download(var, year):
                print(f"!! {var} {year}: no file available (download failed)")
                continue
            try:
                ds = imd.open_data(var, year, year, "yearwise", str(TRUTH)).get_xarray()
                da = clean(ds[list(ds.data_vars)[0]], var)
                if not trusted_reader and grd_path(var, year) is not None:
                    trusted_reader = reader_matches(var, year, da, points)
                    print(f"   raw reader verified against imdlib on {var} {year}: {trusted_reader}")
                src = "imdlib"
            except Exception as e:
                if not trusted_reader:
                    print(f"!! {var} {year}: imdlib could not open it ({e}) and the raw reader is "
                          f"not verified yet (needs one full year first). Skipped.")
                    continue
                try:
                    da = clean(read_grd(grd_path(var, year), var, year), var)
                except Exception as e2:
                    print(f"!! {var} {year}: raw reader failed too ({e2}). Skipped.")
                    continue
                src = "raw reader (partial year)"
            last = pd.Timestamp(da["time"].values[-1]).date()
            print(f"{var} {year}: {da.sizes['time']} days, last {last}  [{src}]")
            rows += extract(da, var, points)

    if not rows:
        raise SystemExit("Nothing usable. Check your connection and re-run.")

    out = pd.concat(rows, ignore_index=True).drop_duplicates(["point_id", "variable", "time"])
    path = TRUTH / "imd_points.parquet"
    out.to_parquet(path, index=False)
    print(f"\nsaved {len(out):,} rows -> {path}")
    print(out.groupby("variable").agg(rows=("value", "size"), valid=("value", "count"),
                                       first=("time", "min"), last=("time", "max")))


if __name__ == "__main__":
    main()
