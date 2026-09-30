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

---

## 2026-09-30: Phase 0 closed

- User said "start the project" without choosing a scheduler option. **Assumption:** use the option with
  no system changes: `scripts/scheduler.py` (APScheduler) started as a background process at
  ~12:40 UTC (runs at 03:30/09:30/15:30/21:30 UTC). It stops if this session/laptop stops; switch to
  Windows Task Scheduler or GitHub Actions when the user decides. Pilot regions kept as proposed.

## 2026-09-30: Phase 1, Adapters and truth

### Verification before coding (rule 10); details in DATA_SOURCES.md
1. **IMD day label** (real data, prototype `check_data.py`, 1,342 day-points, 4 models): Pearson r of
   lead-1 rain vs IMD peaks for windows ending 03 UTC on D (offsets 18–22 h: r ≈ 0.70) vs UTC calendar
   day (0.61). → IMD day D = (D−1 03Z, D 03Z].
2. **Open-Meteo Single Runs retention ≈ 180 days**: earliest run 2026-04-02 for all four models.
   **Deviation from the plan**: no development-period history from Single Runs.
3. **Previous Runs semantics** established by exact 20-location matching: `previous_day{k}` at hour t =
   run floor_6h(t) − k days. Leak-free for nominal 00Z inits, but ~11.5 h staler than a true init.
4. dynamical.org conventions (precip = average rate since previous step; IMERG label = half-hour start;
   IFS-ENS member 0 = control, 00Z only; `ingested_forecast_length` often NaT).
5. ECMWF open data: `tp` accumulated (m), `mx2t3` exists (`mx2t6` does not at step 6).
6. IMD Tmax 2024/2025 downloaded (were missing). **IMD 2026 rain and Tmax not downloadable** (empty
   files; the real-time endpoint timed out).

### Decisions
- **Evaluation sources** (dev and test use the same adapters, so the frozen test has the same semantics):
  dynamical.org true-init for AIFS, GFS, GEFS, IFS-ENS, AIFS-ENS and **IFS control (`ecmwf_ifs_ctrl`, added
  after finding the Previous Runs staleness)**; Previous Runs for IFS HRES, ICON, GEM. Live: Single Runs
  via our archive; ECMWF open data as IFS fallback. Evaluation inits: 00Z only.
- **Canonical contract extended** (rule 4; CLAUDE.md updated): optional `member` dim for ensembles;
  coord `valid_day`; required attr `init_semantics`. New `truth_v1` contract.
- **Regridding without xesmf**: own separable conservative (exact spherical weights) / bilinear /
  identity. All model sources are 0.25° grids containing the IMD points, so identity. Only IMERG (0.1°)
  and IMD Tmax (1°) are actually remapped.
- **Tmax** = max of instantaneous 2 m T at native steps where no max field exists (AIFS/AIFS-ENS 6 h,
  IFS-ENS 3 h, Open-Meteo hourly). 6-hourly sampling underestimates the daily max; left to Phase 3
  bias correction. GFS/GEFS use `maximum_temperature_2m`, ECMWF open data uses `mx2t3`.
- **Live adapter** serves the newest run via Single Runs (the /v1/forecast endpoint does not say which
  init it returned).
- Truth: IMD where available, else IMERG Late flagged `provisional`; no satellite Tmax substitute.
- `scripts/build_canonical.py` **refuses dates overlapping the frozen test period** unless `--allow-test`.

### Missing-value handling (acceptance item)
| Where | Rule |
|---|---|
| Provider nulls (Open-Meteo) | → NaN, never 0; an all-null variable for a whole request = source failure |
| Empty HTTP 200 body | source failure (`SourceUnavailable`), nothing written |
| Window aggregation | any missing interval/sample in the window, or incomplete coverage → window NaN |
| dynamical `ingested_forecast_length` | NaT = unknown (ignored); a recorded length shorter than needed = failure |
| IMD `.grd` | rain < −100 → NaN (−999 code); Tmax ≥ 60 → NaN (99.9 code); sea cells NaN |
| IMERG | a day needs all 48 half-hours finite, else NaN; conservative remap renormalises over valid cells, NaN below 50 % coverage |
| IMD Tmax at coast | one-ring neighbour fill on the 1° grid before bilinear; final truth masked to IMD land cells |
| Negative rain from providers | clipped to 0 (NaN preserved) |
| Missing source at run time | adapter raises; build script logs, reports FAILED and continues with the others |
| NCUM | `NotConfigured` always (not public) |

### Built
| File | What |
|---|---|
| `grid/align.py` | IMD windows, lead windows (00Z → 27…123 h), overlap aggregation for amounts / maxima / samples |
| `grid/regrid.py` | conservative (spherical, NaN-aware), bilinear, identity |
| `grid/canonical.py` | interval/sample series → `canonical_v1` (per-lead series, ensembles) |
| `grid/schema.py` | canonical ensemble dims, `valid_day` consistency check, `truth_v1` |
| `grid/diagnostics.py` | lag-correlation alignment check |
| `adapters/openmeteo_adapters.py` | Previous Runs (half-month cached blocks), Single Runs (via archive), Live |
| `adapters/dynamical.py` | generic dynamical.org adapter, member selection, graceful read failures |
| `adapters/ecmwf_opendata.py` | IFS open-data fallback (tp differences, mx2t3) |
| `adapters/ncum.py`, `adapters/registry.py` | NCUM stub; build adapters from config |
| `truth/imd.py`, `truth/imerg.py`, `truth/build.py` | IMD reader/downloader, IMERG daily, truth builder |
| `io.py` | Windows-safe atomic Zarr swap (fixed a real `PermissionError` crash on re-runs) |
| `scripts/build_canonical.py` | one-command week build + alignment report |

### Real-data results (rain_pilot, 00Z inits 2025-10-20..26, dev period)
All 9 evaluation adapters produced complete canonical data (NaN fraction 0.000 on IMD land cells);
truth 11 IMD days (0 provisional), mean 8.8 mm, one very-heavy cell (116 mm on 2025-10-23).
Report: `data/processed/reports/alignment_rain_pilot_20251020_20251026.md`.

Lead-day-1 lag correlation vs IMD, r(D−1, D, D+1), *sanity check only, not verification*:

| adapter | r(D−1) | r(D) | r(D+1) |
|---|---|---|---|
| ifs_prev | 0.201 | **0.492** | 0.229 |
| ifsctrl_dyn | 0.221 | **0.537** | 0.327 |
| icon_prev | 0.235 | **0.436** | 0.243 |
| gem_prev | 0.159 | **0.466** | 0.185 |
| aifs_dyn | 0.193 | **0.571** | 0.373 |
| gfs_dyn | 0.274 | 0.268 | 0.280 |
| gefs_dyn (mean) | 0.242 | 0.333 | 0.414 |
| ifsens_dyn (mean) | 0.204 | **0.592** | 0.391 |
| aifsens_dyn (mean) | 0.215 | **0.548** | 0.438 |

GFS/GEFS do not peak at D. Investigated: dynamical GFS vs an independent Open-Meteo GFS path agree best
at the same day (r = 0.60/0.70/0.73 at leads 1–3; 0.28–0.53 when shifted a day), so the labels are right.
GFS put this event's peak one day early (lead-1 domain mean 34.6 mm on 10-22 vs observed peak 29.8 mm on
10-23). One week is too small for per-model lag tests; the 1,342-day check above is the alignment evidence.

**heat_pilot, same week** (report `alignment_heat_pilot_20251020_20251026.md`, 11 IMD days, mean rain
4.4 mm, 0 provisional): all 9 adapters complete, and **every source peaks at D**, GFS and GEFS included:
ifs_prev 0.084/**0.513**/0.102, ifsctrl 0.100/**0.539**/0.042, icon 0.026/**0.498**/0.135,
gem −0.030/**0.397**/−0.066, aifs 0.045/**0.610**/0.155, gfs 0.304/**0.417**/0.037,
gefs 0.186/**0.424**/0.119, ifs-ens 0.067/**0.646**/0.096, aifs-ens 0.038/**0.654**/0.105.

Independent end-to-end check: IFS 2026-09-30 00Z via Open-Meteo Single Runs → archive → canonical vs
ECMWF open data GRIB → canonical: rain r = 0.9989, mean |Δ| 0.16 mm; Tmax Δ −0.12 °C.

### Open issues
1. **IMD 2026 truth** (both vars) needed before the Phase 8 frozen test. Retry yearly and real-time
   endpoints; until then 2026 days are IMERG-provisional (rain) and NaN (Tmax).
2. ICON/GEM evaluation data are ~11.5 h staler than true-init sources; skill comparisons must say so.
   GEM stopped on 2026-05-26, so it has no data for most of the test period.
3. AIFS-ENS starts 2025-07-02: only ~6 months of dev data.
4. A first build run died once after `ifs_prev` with no traceback captured; the only reproduced failure was
   the Windows rename error (fixed). Watch for recurrences.
