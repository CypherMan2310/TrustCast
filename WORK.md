# WORK.md

Dated log of work actually completed: what changed, files touched, test results, metrics,
decisions, deviations from plan. Newest entry at the bottom.

---

## 2026-09-30: Phase 0, Foundations

### Starting state
The folder already held a pre-Phase-0 prototype (not written in this session): point-based scripts
`archive_openmeteo.py`, `backfill_previous_runs.py`, `check_data.py`, `download_imd_truth.py`,
`config.py`, `points.csv`, and real data: Open-Meteo Previous Runs for ecmwf_ifs025, gfs_seamless,
icon_seamless and gem_seamless, Jan 2024 – Sep 2026, leads 1–5 d, at 2 points (Kochi, Coimbatore), in
`data/processed/prev_runs/`, 132 cached raw responses in `data/cache/`, IMD `.grd` truth in `data/truth/`
(52 MB), and one live snapshot `data/raw/om_20260930T11.parquet`.

**Decision:** moved all prototype scripts to `prototype/` (data left in place, nothing deleted);
`prototype/config.py` now points at the repo-level `data/`. They are reference material for Phase 1
(the IMD `.grd` raw reader and the 08:30 IST offset check are worth porting).

### Environment
- Machine default Python is 3.14.4. The plan pins 3.12. `py -3.12` → 3.12.10 (Microsoft Store build);
  the other registered 3.12 path (`...\Programs\Python\Python312`) no longer exists.
- `.venv` created with 3.12; direct pins in `requirements.txt`, full freeze in `requirements.lock`.
- Versions: xarray 2026.9.0, zarr 3.4.0, dask 2026.8.0, numpy 2.5.3, pandas 3.0.6, httpx 0.28.1,
  pydantic 2.13.5, dynamical-catalog 1.0.1, duckdb 1.5.6, APScheduler 3.11.3, pytest 9.1.1, ruff 0.16.9.
- `git init` on branch `main` (no remote configured).

### Verification of sources before coding (rule 10); full details in DATA_SOURCES.md
1. Open-Meteo Single Runs accepts `run=` + `forecast_hours=168`; leads 0–167 from init. ✔
2. `ncep_gfs025` on Single Runs → all values null (00Z and 12Z). **Deviation:** GFS archived via `gfs_global`.
3. GEM: metadata last init 2026-05-26; Single Runs returns 400 / empty body. **Deviation:** GEM is
   configured but reported STALE on every run; it contributes no data until it resumes.
4. Quota counts locations: four 273-point requests in about 30 s → HTTP 429 (minutely). **Design change:**
   location-weighted limiter, 400/min blocking and 4000/h non-blocking; lookback lowered from 4 to 2
   cycles so a first run (~3,500 location-calls) fits in the hourly quota.
5. `cell_selection` default "land" moves coastal points, so we always send `nearest`.
6. AIFS is 6-hourly natively and IFS 3-hourly; the IMD 03 UTC day boundary is not on the AIFS grid.
   Recorded for Phase 1 alignment.
7. dynamical.org: all planned datasets exist with the ranges in DATA_SOURCES.md. IFS-ENS and GEFS are
   **00Z daily only**. IMERG Early/Late is on dynamical.org anonymously, so no Earthdata login is needed
   for recent-day truth (plan assumed GES DISC).

### Assumptions (logged per protocol)
- **Pilot regions:** rain = Kerala + coastal Karnataka, 8.0–13.0 N, 74.5–77.5 E (273 IMD cells; covers the
  Wayanad Jul-2024 replay and extends the prototype's Kochi/Coimbatore points). Heat = Vidarbha, 19.0–22.0 N,
  77.0–80.0 E (169 cells; 2024 heatwave). The cyclone replays (Remal, Dana, Fengal) fall outside both and
  will need an extra region or a national run in Phase 7. Change in `config/pilot.yaml` if you prefer others.
- **Archive schema:** the archiver stores native hourly output (`archive_hourly_v1`), not the canonical
  24 h product. Accumulation and alignment are Phase 1, where they get their own tests. This keeps raw data
  reusable if the alignment rule changes.
- **One Zarr store per run** (`<source>/<region>/<stamp>.zarr`), which chunks naturally along `init_time`
  and keeps each run immutable. Phase 1 opens them lazily with `open_mfdataset`.
- **Package path:** code lives in `src/trustcast/<module>/` instead of the plan's `src/<module>/`, so it
  is an importable package. Same module names.
- **Stale ≠ failure** for the exit code: a STALE source is logged at ERROR and recorded in `runs.jsonl`
  but does not fail the cron job (GEM would otherwise fail every run). Fetch or verification failures → exit 1.

### Built
| File | What |
|---|---|
| `config/pilot.yaml`, `src/trustcast/config.py` | typed YAML config (grid, regions, archiver, sources) |
| `src/trustcast/log.py` | JSON-lines logging |
| `src/trustcast/grid/imd_grid.py` | IMD 0.25°/1.0° grids, exact on-grid bbox subsetting |
| `src/trustcast/grid/schema.py` | `archive_hourly_v1` + `canonical_v1` contracts and validators |
| `src/trustcast/adapters/base.py` | `SourceAdapter` ABC; `SourceUnavailable`, `StaleSource`, `NotConfigured` |
| `src/trustcast/adapters/ratelimit.py` | rolling-window limiter (blocking / non-blocking) |
| `src/trustcast/adapters/openmeteo.py` | Single Runs client: metadata, batched fetch, retries, JSON → Dataset |
| `src/trustcast/archive/{cycles,manifest,runner}.py` | cycle choice, SHA-256 manifests + verification, idempotent runner |
| `scripts/archive_run.py`, `scripts/verify_archive.py`, `scripts/scheduler.py` | CLI, re-verification, APScheduler |
| `.github/workflows/archive.yml` | cron 09:30/21:30 UTC, tests, archive, verify, upload data as artifact |
| `tests/` | 32 offline tests + 1 `live` test; `tests/fixtures/synthetic_openmeteo.py` labelled SYNTHETIC |

### Tests
`pytest -q` → **32 passed, 1 deselected (live)**. `ruff check` and `ruff format --check`: clean.
`pytest -m live` → **1 passed** (real IFS single point).

### Acceptance run (real data), 2026-09-30 12:04–12:15 UTC
`python scripts/archive_run.py` → exit 0, 11 min 6 s (throttled at 400 locations/min).

| source | cycles archived | regions | status |
|---|---|---|---|
| ecmwf_ifs | 2026-09-29 12Z, 2026-09-30 00Z | rain_pilot, heat_pilot | ok ×4 |
| ecmwf_aifs | same | same | ok ×4 |
| ncep_gfs (`gfs_global`) | same | same | ok ×4 |
| dwd_icon (`icon_global`) | same | same | ok ×4 |
| cmc_gem | none | both | **stale** (newest run 2026-05-26 00Z) |

- `python scripts/verify_archive.py` → **16/16 manifests verified** (raw SHA-256, Zarr opens, schema valid,
  per-variable digests match).
- Rerun → 16 `exists`, 2 `stale`, 4.3 s, nothing fetched (idempotent).
- Size: raw 984 KB, processed 1.8 MB for 16 runs (about 170 KB/run). Projection: ~16 runs/day → ~2.7 MB/day, ~1 GB/yr.
- NaN fraction: t2m 0.0000; precip 0.0060 (= lead 0 only, 1/168, expected).
- Sanity check (00Z run, first IMD-style day 04Z→03Z, *indicative only, not verification*): rain pilot
  mean 24 h rain 1.8–5.1 mm, cell max 10.5 (AIFS) to 50.2 mm (GFS); heat pilot ≈ 0 mm in all models
  (consistent with monsoon withdrawal from Vidarbha). t2m ranges 10–39 °C (low end = high Western Ghats).
- Provider-cell offset from IMD points: 0.000° for IFS, AIFS, ICON; **up to 0.079° for `gfs_global`**
  (not a pure 0.25° grid). Recorded for Phase 1 regridding.

### Open questions for the user
1. **Where should the scheduler run?** Options: (a) GitHub Actions: needs a GitHub remote; data is uploaded
   as 90-day artifacts that must be pulled locally; (b) Windows Task Scheduler on this laptop running
   `scripts/archive_run.py` at 03:30/09:30/15:30/21:30 UTC; (c) `scripts/scheduler.py` left running.
   Until one is chosen, each missed day loses nothing for IFS (Single Runs history from Mar 2024) but
   non-IFS Single Runs history depends on Open-Meteo retention.
2. Pilot regions (assumption above): keep Kerala/coastal Karnataka + Vidarbha?

### Phase 0 status
All acceptance checks pass except the **scheduler being live**, which needs question 1 answered.
