# CLAUDE.md: TRUSTCAST (SIH26081)

Anti-hallucination anchor. **Re-read at the start of every session.** Source of truth for scope is
`SIH26081_BUILD_PLAN.md`; if this file and the plan disagree, stop and ask the user.

TRUSTCAST is a Smart India Hackathon 2026 submission for **SIH26081, Hybrid AI–NWP Multi-Model Forecast
Blending System** (NCMRWF, MoES; theme Disaster Management; software). It learns each forecast source's
skill from verification against IMD observations, blends sources adaptively into one bias-corrected,
calibrated forecast, preserves extremes, quantifies uncertainty, explains itself, and serves an API +
dashboard.

---

## 1. Strict rules (verbatim from the master prompt; non-negotiable)

1. **No fabricated data.** Real data only in the pipeline, the API and the UI. If a source is unreachable, fail loudly, log it, and degrade gracefully. Never silently substitute synthetic values. Synthetic fixtures are allowed only in `tests/` and must be labelled as such.
2. **No leakage.** A forecast issued at time t may use only verification data whose valid time ≤ t. Write and keep a unit test that proves this.
3. **Frozen test set.** Development: Jan 2024 – Dec 2025. Held-out test: Jan – Sep 2026. Never tune on the test set. Run the final test evaluation once, at Phase 8, and record it.
4. **Contract-first.** Define schemas (xarray schema, Pydantic API models, OpenAPI) before implementations. Do not change a contract without updating the plan, `CLAUDE.md`, and all consumers.
5. **Every layer earns its place.** A model layer ships only if it beats the previous layer on the development split (paired block bootstrap, 5-day blocks). If it does not, keep the code, disable it, and log the result in `WORK.md`.
6. **Honest reporting.** Report metrics with 95% intervals. Report where the blend is not better. Never cherry-pick.
7. **Respect data terms.** Prefer APIs, bulk downloads and open buckets over scraping. Any scraping must honour robots.txt and site terms, rate-limit itself (seconds between requests), cache aggressively, and never touch anything behind a login. Record each source, access date and licence in `DATA_SOURCES.md`. Attribute CC BY data.
8. **Decision-support only.** Every UI page, bulletin and alert carries: "Decision-support tool. Not an official warning."
9. **No secrets in the repo.** Keys (e.g. Copernicus CDS, NASA Earthdata) go in `.env`, with `.env.example` committed.
10. **Verify before you assume.** Confirm package APIs, dataset IDs, URLs and init-time ranges against live docs or a real request before coding against them. If something differs from the plan, record it in `DATA_SOURCES.md` and `WORK.md`.

### Working protocol
- Files: `CLAUDE.md` (this), `TODO.md` (work items + acceptance checks; tick only when tests pass),
  `WORK.md` (dated log of what was actually done), `DATA_SOURCES.md` (every source, access date, licence).
- End of every module: run tests → update `TODO.md` → append `WORK.md` → update `CLAUDE.md` if
  architecture/contracts changed. Do not start the next module before all four are done.
- STOP gates after Phase 2, Phase 5 and Phase 8: report and wait for the user's go-ahead.
- Ask at most one clarifying question at a time, only when blocked; otherwise assume, state, and log.
- Never claim a metric not computed or a test not run.

---

## 2. Architecture

```
 SOURCES (adapters)                  CORE                                  PRODUCT
 NWP: IFS, GFS, ICON, (GEM)   ─▶  1 Ingest → archive_hourly_v1 Zarr   ─▶  FastAPI /v1/...
 AI:  AIFS Single                 2 Align → canonical_v1 (IMD grid,        Next.js + MapLibre
 ENS: GEFS, IFS-ENS, AIFS-ENS       08:30–08:30 IST day)                   Alerts: bulletin, CAP
 (NCUM/NEPS stub)                 3 Bias-correct (quantile mapping)
 TRUTH: IMD grid, IMERG, ERA5 ─▶  4 Skill tracker (leak-free, decayed)
                                  5 Blender A (1/MSE^p) → B (LightGBM gate)
                                  6 Extremes  7 Uncertainty (CQR)
                                  8 Defer flag + explainability  9 Verification harness
```

Layer order and gates: L0 baselines → L1 bias correction → L2 skill tracker → L3A decayed blender →
L3B gated blender → L4 regimes → L5 extremes → L6 uncertainty → L7 defer/explain → L8 degradation.

### Phase status
| Phase | Status |
|---|---|
| 0 Foundations (repo, convention files, archiver) | done except live scheduling (awaiting user choice) |
| 1–8 | not started |

---

## 3. Tech stack (fixed unless a step fails; deviations logged in WORK.md)

- **Python 3.12** in `.venv` (created with `py -3.12 -m venv .venv`; the machine default is 3.14; do not use it).
- xarray, zarr (v3 format, unconsolidated stores), dask, numpy, pandas, scipy, pyarrow, duckdb, pydantic,
  httpx, PyYAML, APScheduler, dynamical-catalog, pytest, ruff. Later: scikit-learn, lightgbm, shap,
  fastapi, uvicorn, imdlib, xesmf or xarray-regrid, cdsapi/earthaccess (optional).
- Frontend (Phase 6): Next.js (TypeScript), MapLibre GL, ECharts or Recharts, Tailwind.
- Storage: raw files → Zarr → Parquet (DuckDB); SQLite for app state.
- Scheduling: `scripts/scheduler.py` (APScheduler) locally + `.github/workflows/archive.yml`.
- Pins: `requirements.txt` (direct), `requirements.lock` (full freeze).

---

## 4. Directory layout

```
TrustCast/
  CLAUDE.md TODO.md WORK.md DATA_SOURCES.md SIH26081_BUILD_PLAN.md
  pyproject.toml requirements.txt requirements.lock .env.example .gitignore
  config/pilot.yaml              grid, regions, archiver, source list (single config source)
  src/trustcast/
    config.py log.py
    adapters/  base.py (SourceAdapter, errors) ratelimit.py openmeteo.py
    grid/      imd_grid.py (IMD grids, bbox) schema.py (xarray contracts)
    archive/   cycles.py manifest.py runner.py
    bias/ skill/ blend/ extremes/ uncertainty/ verify/ api/ alerts/   (later phases)
  scripts/   archive_run.py verify_archive.py scheduler.py
  tests/     unit tests; tests/fixtures/ = SYNTHETIC fixtures only
  prototype/ pre-Phase-0 point scripts (Previous Runs backfill, IMD truth) kept for reference
  web/ notebooks/ .github/workflows/
  data/ (git-ignored)
    raw/openmeteo/<source>/<region>/<YYYYmmddTHH>.json.gz        immutable raw responses
    processed/archive/<source>/<region>/<YYYYmmddTHH>.zarr        archive_hourly_v1
    processed/archive/manifests/<source>__<region>__<stamp>.json manifest per run
    processed/archive/runs.jsonl                                  one line per attempt
    logs/archiver.jsonl                                           structured logs
    cache/ processed/prev_runs/ truth/                            prototype outputs (real data)
```

Package imports: scripts and tests put `src/` on `sys.path`; run everything with `.venv/Scripts/python`.

---

## 5. Data contracts

### Grid
IMD 0.25° rain grid: lat 6.5–38.5 N, lon 66.5–100.0 E, 129 × 135 (`IMD_RAIN_0P25`). IMD Tmax is 1.0°
(lat 7.5–37.5, lon 67.5–97.5; `IMD_TEMP_1P0`). Region bounds must lie exactly on the grid.

### Pilot regions (`config/pilot.yaml`)
- `rain_pilot`: lat 8.0–13.0, lon 74.5–77.5 (21 × 13 = 273 pts), Kerala + coastal Karnataka.
- `heat_pilot`: lat 19.0–22.0, lon 77.0–80.0 (13 × 13 = 169 pts), Vidarbha.

### `archive_hourly_v1` (Phase 0 archiver output; `grid/schema.py::validate_archive`)
- dims `(init_time, lead_h, lat, lon)`; `lead_h` = 0..167 hours from init.
- vars `precip_1h_mm` (float32, precipitation in hour ending at valid_time), `t2m_c` (float32).
- coords `valid_time(init_time, lead_h)`, `model_lat/model_lon(lat, lon)` (provider's nearest cell).
- attrs `schema, source, provider, model_id, model_version, licence, fetched_at, regrid_method, region, init_time`.
- Values exactly as delivered: provider nulls → NaN, never 0. No accumulation, no interpolation.

### `canonical_v1` (Phase 1 target; `grid/schema.py::validate_canonical`)
- dims `(init_time, lead_h, lat, lon)` on the IMD 0.25° grid.
- vars `precip_24h_mm` (accumulated over the IMD day 03:00→03:00 UTC = 08:30→08:30 IST), `tmax_c`.
  Extend later: `wind_gust_ms`, `mslp_hpa`.
- `lead_h` = hours from init to the END of the 24 h window.
- attrs `schema, source, model_version, licence, fetched_at, regrid_method`.

### Truth (Phase 1)
Same grid, dim `time`, vars `rain_mm`, `tmax_c`, plus `provisional` flag (satellite-filled recent days).

### Skill table (Parquet, Phase 2+)
`source, variable, cell_or_subdivision, lead_bucket, season, valid_time, error, abs_error, sq_error,
event_hit_flags, regime`.

### Manifest (`trustcast.manifest.v1`, `archive/manifest.py`)
source, provider, model_id, licence, region, init_time, fetched_at, bbox, request, duration_s,
code_version, raw {path, sha256, bytes}, processed {path, schema, dims, variables{dtype, shape,
nan_fraction, min, max, sha256 of float32 values}}. `verify_manifest()` re-hashes everything.

### Splits
Dev Jan 2024 – Dec 2025 (rolling-origin CV). Test Jan – Sep 2026, frozen, run once at Phase 8.

### API contract (Phase 6; to be written as Pydantic/OpenAPI before implementation)
`GET /v1/health, /v1/sources, /v1/forecast/blend?lat&lon&variable&init, /v1/forecast/grid,
/v1/skill/map, /v1/skill/leaderboard, /v1/verification/summary, /v1/alerts/district,
/v1/explain/{district}, /v1/bulletin/{district}, /v1/replay/{event_id}`, `POST /v1/feedback/override`.
Every response carries the disclaimer (`trustcast.DISCLAIMER`).

---

## 6. Source facts verified live (details and dates in DATA_SOURCES.md)

- Open-Meteo Single Runs: `run=<init>` + `forecast_hours=N` gives leads 0..N-1 from init. Ids that work:
  `ecmwf_ifs025`, `ecmwf_aifs025_single`, `gfs_global`, `icon_global`. **`ncep_gfs025` returns all-NaN**;
  **GEM (`gem_global`) has no runs since 2026-05-26** (archiver flags it STALE).
- Open-Meteo quota counts each location as a call: 600/min, 5000/h, 10000/day. Throttle: 400/min
  (blocking), 4000/h (non-blocking; fail and resume next run).
- Use `cell_selection=nearest` (default "land" shifts coastal points).
- Native steps: IFS 3 h, AIFS 6 h (Open-Meteo spreads it to hourly), GFS/ICON 1 h. The 03 UTC IMD day
  boundary does not fall on the AIFS 6 h grid; handle explicitly in Phase 1 alignment.
- dynamical.org keeps full history (no snapshotting needed): AIFS Single 6-hourly from 2024-04-01, AIFS
  ENS from 2025-07-02, IFS ENS 0.25° 00Z daily from 2024-04-01, GEFS 35-day 00Z daily from 2020-10,
  GFS from 2021-05, IMERG Early/Late 30-min from 1998. All CC BY 4.0.

---

## 7. Coding standards

- Typed Python, docstrings on public functions, `ruff check` + `ruff format` clean, pytest for every module.
- Mandatory tests: leakage, alignment, schema, bootstrap, degradation.
- Deterministic: fixed seeds, pinned versions, config in YAML.
- Structured JSON logs; every fetch logs source, bbox, init_time, duration, status.
- Lazy dask/Zarr reads, chunk along `init_time`/`lead_h`; never load full archives into memory.
- Network tests are marked `@pytest.mark.live` and excluded by default (`pytest -m live` to run).
- Small commits, one module per commit series; commit trailer per session instructions.
