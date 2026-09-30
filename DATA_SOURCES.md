# DATA_SOURCES.md

Every data source TRUSTCAST touches: how it is accessed, when it was checked, its licence, and any
behaviour that differs from `SIH26081_BUILD_PLAN.md`. Update on every new source or observed change.

Attribution line for UI, bulletins and reports:
> Forecast data: Open-Meteo.com (CC BY 4.0), with model data from ECMWF, NOAA/NCEP, DWD and ECCC;
> dynamical.org (CC BY 4.0); ECMWF open data (CC BY 4.0). Observations: India Meteorological
> Department; NASA GPM IMERG V07 via dynamical.org (CC BY 4.0).

## Source matrix (Phase 1, 2026-09-30)

| Logical source | Evaluation history (dev 2024–25, test 2026) | Live | Init semantics in eval |
|---|---|---|---|
| `ecmwf_ifs_ctrl` | dynamical IFS-ENS member 0 (control), 00Z, from 2024-04-01 | same | true init |
| `ecmwf_ifs` (HRES) | Open-Meteo Previous Runs `ecmwf_ifs025` | Single Runs / own archive; ECMWF open data fallback | nominal init, **~11.5 h staler** |
| `ecmwf_aifs` | dynamical AIFS Single, from 2024-04-01 | Single Runs / archive | true init |
| `ncep_gfs` | dynamical GFS, from 2021-05 | Single Runs / archive | true init |
| `dwd_icon` | Open-Meteo Previous Runs `icon_global` | Single Runs / archive | nominal init, ~11.5 h staler |
| `cmc_gem` | Open-Meteo Previous Runs `gem_global` (until provider stopped, 2026-05-26) | none (stale) | nominal init, ~11.5 h staler |
| `ncep_gefs` (31 members) | dynamical GEFS 35-day, 00Z | same | true init |
| `ecmwf_ifs_ens` (51) | dynamical IFS-ENS 0.25°, 00Z | same | true init |
| `ecmwf_aifs_ens` (51) | dynamical AIFS-ENS, **from 2025-07-02 only** | same | true init |
| `ncmrwf_ncum` | not public | not public | `NotConfigured` stub |

Truth: IMD gridded rain 0.25° + Tmax 1.0° (gauge, final); IMERG V07 Late (provisional) where IMD is
not available.

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
- **Retention is a rolling ~180 days (checked 2026-09-30):** binary search over 00Z runs gives the
  earliest available run = **2026-04-02 for all four models** (ecmwf_ifs025, ecmwf_aifs025_single,
  gfs_global, icon_global). A 2025-10-20 request returns HTTP 400 "requested model run is not
  available". **Deviation from the plan** (which says IFS from Mar 2024, others from Sep 2025): Single
  Runs gives no development-period data. Our own archiver is the only way to keep these runs.
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

### Open-Meteo Previous Runs API (evaluation history for IFS HRES, ICON, GEM)

**Semantics, verified 2026-09-30.** `<var>_previous_day{k}` at valid hour t is the value from the run
initialised at **floor_6h(t) − k days**. Evidence: for 2026-09-20, 20 locations, the full 20-location
vector matched a Single Runs run exactly (|Δ| ≤ 0.05 °C) at the model's native 3-hourly steps:
hours 00/03 → run 09-19 00Z, 06/09 → 06Z, 12/15 → 12Z, 18/21 → 18Z (day1), and the same pattern a day
earlier for day2. Intermediate hours differ slightly (the two APIs interpolate 3 h → 1 h differently).
Consequences:
- A Previous Runs "lead day" mixes four runs (00/06/12/18Z). For a nominal 00Z init I, lead day k uses
  `previous_day{k}` and every run used is initialised in [I − 1 day, I], so nothing after I (leak-free;
  unit-tested in `tests/test_canonical.py`).
- Effective lead is 24k … 24k+5 h (mean ≈ 24k+2.5 h), versus 24k−21 … 24k+3 h (mean ≈ 24k−9 h) for a
  true 00Z run: **Previous Runs sources are ~11.5 h staler** at the same nominal lead. Skill comparisons
  must keep this in mind; `ecmwf_ifs_ctrl` (true init) was added for a fair IFS.
- Model ids that work for 2025-10: `ecmwf_ifs025`, `icon_global`, `icon_seamless`, `gem_global`,
  `gem_seamless`, `ecmwf_aifs025_single`. GEM cells sit ~0.05° off the IMD points (nearest cell).
- Quota weight ≈ locations × max(1, n_vars/10) × max(1, n_days/14); blocks are half-months (1–14,
  15–end), cached as raw gzip under `data/raw/openmeteo_prev/<model>/<region>/` once complete.

Prototype data (collected before Phase 0, `prototype/backfill_previous_runs.py`):
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

Conventions (dataset attributes and catalogue pages, 2026-09-30):
- `precipitation_surface`: **average rate (kg m⁻² s⁻¹ = mm/s) since the previous forecast step**
  (`step_type: avg`); step amount = rate × step length. IMERG: mean rate over the half hour
  **starting** at the time label (catalogue page), gauge-adjusted where available (Late run, ~14 h latency).
- `temperature_2m` instantaneous; `maximum_temperature_2m` (GFS, GEFS) = max since the previous step.
- Native lead steps: AIFS/AIFS-ENS 6 h; IFS-ENS 3 h; GEFS 3 h; GFS 1 h (then 3 h).
- IFS-ENS: 51 members, **member 0 = control** ("produced with the best available data and unperturbed
  models"); **00Z inits only**. GEFS 35-day: 00Z only.
- `ingested_forecast_length` is often NaT even when data is present; treated as "not recorded".
- Grids are 0.25° global, latitude descending; IMD 0.25° points coincide exactly (identity selection).
- Read time for one init, rain pilot: AIFS ~13–18 s, GFS ~20 s, IFS-ENS ~5 s, AIFS-ENS ~6 s, GEFS ~38 s.

### ECMWF open data (IFS HRES fallback, `ecmwf-opendata` 0.3.34 + cfgrib/eccodes 2.48)
| Item | Value |
|---|---|
| Access | `Client(source="ecmwf", model="ifs", resol="0p25").retrieve(...)`, anonymous |
| Licence | CC BY 4.0, attribute ECMWF (shown by the client on download) |
| Checked | 2026-09-30: latest 00Z = 2026-09-30 00Z |
| Params | `tp` accumulated from init (m); `mx2t3` = max 2 m T over previous 3 h (K); `mx2t6` not found at step 6; `2t` |
| Size | ~0.6–0.8 MB per global field; ~30 MB per run for our windows |
| Notes | Recent runs only (days). Portal limited to 500 simultaneous connections; mirrors on AWS/Azure/GCP |

Cross-check 2026-09-30 00Z IFS, rain pilot, 5 IMD days: Open-Meteo Single Runs (via our archive) vs
ECMWF open data → 24 h rain r = 0.9989, mean |Δ| = 0.16 mm; Tmax mean Δ = −0.12 °C (hourly-sampled
2 m T vs true 3-hourly maxima).

### IMD gridded rainfall and Tmax (prototype truth, `prototype/download_imd_truth.py`)
| Item | Value |
|---|---|
| Access | `imdlib` → imdpune.gov.in yearly `.grd` files; raw reader for the partial current year, verified against imdlib on a full year |
| Grids | rain 0.25° (129 × 135 from 6.5 N / 66.5 E); Tmax 1.0° (31 × 31 from 7.5 N / 67.5 E) |
| Missing codes | rain `-999` (mask `< -100`), Tmax `99.9` (mask `>= 60`) |
| Data on disk | `data/truth/` (52 MB): yearly `.grd` files + `imd_points.parquet` at the prototype points |
| Licence | IMD data, free for research use; attribute India Meteorological Department. Exact terms still **to confirm** on imdpune.gov.in |
| Files present (2026-09-30) | rain 2024, 2025 (complete); Tmax 2024, 2025 (complete, files named `YYYY.GRD`) |
| **2026 missing** | `imdlib.get_data` for 2026 (rain and Tmax) reports success but leaves an empty file (3 attempts each). The real-time endpoint `cmpg/Realtimedata/Rainfall/rain.php` timed out. Needed before the Phase 8 frozen test; until then 2026 days use IMERG, flagged `provisional`. |
| Day label | IMD day D = 24 h ending 08:30 IST (03 UTC) on D. Checked on 1,342 day–point pairs (4 models, lead 1): correlation vs window offset peaks at windows ending 03 UTC on D (r ≈ 0.70); UTC calendar day r ≈ 0.61 |
| Reader | Own raw reader (`truth/imd.py`), identical to `imdlib.open_data` on the full 2024 rain and Tmax files |

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

---

## Added 2026-09-30 (Phases 3-8)

### geoBoundaries (district aggregation, alerts, CAP polygons)
| Item | Value |
|---|---|
| ADM2 | gbOpen IND ADM2 (2021, 735 features), source Pathways Data Pvt. Ltd. / lgdirectory.gov.in, **ODbL 1.0** |
| ADM1 | gbOpen IND ADM1 (36), DataMeet India / Election Commission of India, **CC BY 2.5 IN** |
| Access | geoBoundaries API metadata, simplified GeoJSON from github.com/wmgeolab/geoBoundaries (commit 9469f09) |
| Checked | 2026-09-30 |

### Terrain
Point elevations from the `elevation` field of our archived Open-Meteo responses (Open-Meteo documents
Copernicus DEM GLO-90); slope and distance to coast derived on the 0.25° grid. No extra download.

### ECMWF model change inside the test period
IFS Cycle 50r1 and AIFS Single/ENS v2 went operational with the 06 UTC run of 12 May 2026 (ECMWF news
item 2026-05-12; ECMWF forum confirmation 2026-05-06). Phase 8 reports before/after 2026-05-13 00Z.

### Basemap (dashboard only)
CARTO raster basemaps (light_all / dark_all), attribution "© OpenStreetMap contributors © CARTO".
