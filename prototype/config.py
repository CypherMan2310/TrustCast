"""Shared settings for the TrustCast data scripts."""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent          # prototype/ (moved here in Phase 0, 2026-09-30)
DATA = ROOT.parent / "data"                     # shared repo-level data/ folder
RAW = DATA / "raw"                    # live snapshots from archive_openmeteo.py
CACHE = DATA / "cache"                # raw API responses, so nothing is fetched twice
PREV = DATA / "processed" / "prev_runs"
TRUTH = DATA / "truth"
POINTS_CSV = ROOT / "points.csv"

# Open-Meteo model ids. If one is rejected, the error message says so: rename or remove it.
MODELS = ["ecmwf_ifs025", "gfs_seamless", "icon_seamless", "gem_seamless"]
VARS = ["precipitation", "temperature_2m"]
LEADS = [1, 2, 3, 4, 5]               # forecast lead in days (Previous Runs API supports 1-7)
DEFAULT_START = "2024-01-01"


def load_points() -> pd.DataFrame:
    """Read points.csv (columns: id, name, lat, lon). Creates an editable sample if missing."""
    if not POINTS_CSV.exists():
        pd.DataFrame(
            {
                "id": [0, 1],
                "name": ["Kochi (sample)", "Coimbatore (sample)"],
                "lat": [9.93, 11.00],
                "lon": [76.27, 76.96],
            }
        ).to_csv(POINTS_CSV, index=False)
        print(f"Created sample {POINTS_CSV.name} - EDIT IT with your pilot district centroids.")
    return pd.read_csv(POINTS_CSV)
