# DATA_SOURCES.md

Every data source TRUSTCAST touches: how it is accessed, when it was checked, its licence, and any
behaviour that differs from `SIH26081_BUILD_PLAN.md`. Update on every new source or observed change.

Attribution line for UI, bulletins and reports:
> Forecast data: Open-Meteo.com (CC BY 4.0), with model data from ECMWF, NOAA/NCEP, DWD and ECCC;
> dynamical.org (CC BY 4.0). Observations: India Meteorological Department; NASA GPM IMERG.

---

## In use

### Open-Meteo Single Runs API (Phase 0 archiver)
| Item | Value |
|---|---|
| Endpoint | `https://single-runs-api.open-meteo.com/v1/forecast` |
| Access | HTTP GET, anonymous, multi-location (comma-separated lat/lon) |
| Licence | CC BY 4.0; free API for non-commercial use (open-meteo.com/en/terms) |
| Checked | 2026-09-30, live requests |
| Used for | 00/12Z snapshots of IFS, AIFS, GFS, ICON (and GEM, currently stale) for pilot regions |

Observed behaviour (2026-09-30):
- `run=YYYY-MM-DDTHH:MM` selects the init; with `forecast_hours=168` the hourly axis runs init → init+167 h.
  First precipitation step is null (no accumulation at t=0).
- Model ids: `ecmwf_ifs025` OK, `ecmwf_aifs025_single` OK, `icon_global` and `dwd_icon` OK,
  `gfs_global` / `gfs_seamless` OK. **`ncep_gfs025` returns HTTP 200 with every value null** (00Z and 12Z),
  so GFS is archived via `gfs_global`. `ncep_gfs013` returned an empty body for a 12Z run.
- **GEM:** `gem_global` returns 400 "requested model run is not available" for 2026-05-26 00Z and an empty
  body for 2026-09-29 12Z. Metadata shows the last GEM init as 2026-05-26 00Z. GEM is kept in the config so
  the archiver records it as STALE on every run. It is not used as a source until it resumes.
- An empty 200 body means "run not available"; the client treats it as a failure.
- Quota: each **location** counts as one call. Four 273-point requests inside one minute returned HTTP 429
  "Minutely API request limit exceeded". Documented free limits: 600/min, 5000/h, 10000/day.
  TRUSTCAST throttles to 400 locations/min (blocking) and 4000/h (fail, resume next run).
- Default `cell_selection=land` moved a requested coastal point (10.0, 76.0) to lon 76.25. We always send
  `cell_selection=nearest` and store the provider's cell as `model_lat/model_lon`.
- Native time steps (metadata `temporal_resolution_seconds`): IFS 3 h, AIFS 6 h, GFS 1 h, ICON 1 h. AIFS
  hourly precipitation is non-zero in 143/168 steps for one test point, which suggests Open-Meteo spreads the
  6 h totals across hours. The 03 UTC IMD day boundary is not on the AIFS 6 h grid; Phase 1 must handle it.

### Open-Meteo model metadata
| Item | Value |
|---|---|
| Endpoint | `https://api.open-meteo.com/data/<meta_id>/static/meta.json` |
| Fields used | `last_run_initialisation_time` (unix s) |
| Checked | 2026-09-30 |

Latest inits seen 2026-09-30 ~11:50 UTC: ecmwf_ifs025 2026-09-30 00Z, ncep_gfs025 00Z, dwd_icon 06Z,
ecmwf_aifs025_single 00Z, **cmc_gem_gdps 2026-05-26 00Z**. `gem_global`/`gem_seamless` have no
`last_run_initialisation_time`.

### Open-Meteo Previous Runs API (prototype backfill, `prototype/backfill_previous_runs.py`)
| Item | Value |
|---|---|
| Endpoint | `https://previous-runs-api.open-meteo.com/v1/forecast` |
| Licence | CC BY 4.0, non-commercial |
| Data on disk | `data/processed/prev_runs/<model>_<YYYYMM>.parquet`: ecmwf_ifs025, gfs_seamless, icon_seamless, gem_seamless, Jan 2024 – Sep 2026, lead days 1–5, at the 2 prototype points (Kochi, Coimbatore) |
| Raw cache | `data/cache/*.json` (132 files) |
| Collected | before Phase 0 (files dated 2026-09-30) |

### dynamical.org catalog (Phase 1 adapters; checked, not yet ingested)
| Item | Value |
|---|---|
| Access | `pip install dynamical-catalog` (1.0.1); `dynamical_catalog.open("<id>")`, anonymous Zarr |
| Licence | CC BY 4.0 (dataset attrs) |
| Checked | 2026-09-30 |

| Dataset id | init/time range seen | step | notes |
|---|---|---|---|
| `ecmwf-aifs-single-forecast` | 2024-04-01 00Z → 2026-09-30 00Z | 6 h inits | lead 0–360 h, 6-hourly; `precipitation_surface`, `temperature_2m` |
| `ecmwf-aifs-ens-forecast` | 2025-07-02 → 2026-09-30 | 6 h inits | 51 members |
| `ecmwf-ifs-ens-forecast-15-day-0-25-degree` | 2024-04-01 → 2026-09-30 | **00Z daily only** | 51 members, lead 3-hourly to 360 h |
| `noaa-gefs-forecast-35-day` | 2020-10-01 → 2026-09-30 | **00Z daily only** | 31 members, 3-hourly leads; has `maximum_temperature_2m` |
| `noaa-gfs-forecast` | 2021-05-01 → 2026-09-30 06Z | 6 h inits | hourly leads to 384 h; has `maximum_temperature_2m` |
| `nasa-imerg-analysis-late` | 1998-01-01 → 2026-09-29 20:30 | 30 min | 0.1°; truth for recent days, **no Earthdata login needed** |
| `nasa-imerg-analysis-early` | 1998-01-01 → 2026-09-30 06:30 | 30 min | 0.1° |

dynamical.org keeps its own history, so the archiver does not snapshot these sources.

### IMD gridded rainfall and Tmax (prototype truth, `prototype/download_imd_truth.py`)
| Item | Value |
|---|---|
| Access | `imdlib` → imdpune.gov.in yearly `.grd` files; raw reader for the partial current year, verified against imdlib on a full year |
| Grids | rain 0.25° (129 × 135 from 6.5 N / 66.5 E); Tmax 1.0° (31 × 31 from 7.5 N / 67.5 E) |
| Missing codes | rain `-999` (mask `< -100`), Tmax `99.9` (mask `>= 60`) |
| Data on disk | `data/truth/` (52 MB): yearly `.grd` files + `imd_points.parquet` at the prototype points |
| Licence | IMD data, free for research use; attribute India Meteorological Department. Exact terms still **to confirm** on imdpune.gov.in |

---

## Planned (not yet accessed in code)

| Source | Use | Access | Status |
|---|---|---|---|
| ECMWF Open Data | IFS/AIFS fallback | `ecmwf-opendata` / buckets | Phase 1 fallback adapter |
| NOAA GFS/GEFS on AWS | GFS history fallback | `s3://noaa-gfs-bdp-pds` (no-sign) | Phase 1 fallback adapter |
| NCMRWF NCUM/NEPS | Extra sources | Not public | `NcumAdapter` stub raises `NotConfigured` |
| ERA5 (CDS) | Regime features | `cdsapi` + key in `.env` | optional |
| DataMeet / LGD boundaries | District/subdivision aggregation | GitHub / lgdirectory | Phase 2+ |
| Copernicus DEM, Natural Earth | Terrain / coast features | direct download | Phase 4 |
| NDMA SACHET | CAP format reference | sachet.ndma.gov.in | Phase 7 |
| BoM RMM index | Optional MJO regime | bom.gov.au | Phase 4, optional |
