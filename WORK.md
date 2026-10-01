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

---

## 2026-09-30: Phase 2, verification harness (data backfill running)

User: "continue as existing", i.e. go ahead with the recommendation: Previous Runs on IMD land cells
only, GEM kept for the development years, backfill now in the background.

### Built
| File | What |
|---|---|
| `adapters/ledger.py` | cross-process Open-Meteo quota ledger (archiver cap 9,500, backfill 8,000 per 24 h) |
| `adapters/base.py` | `QuotaExhausted` (retry later) vs `SourceUnavailable` (source broken) |
| `adapters/openmeteo_adapters.py` | Previous Runs requests IMD land cells only (`*_land_L5` cache blocks) |
| `scripts/backfill_canonical.py` | monthly canonical stores, resumable; sleeps to 00:10 UTC on the daily limit; 2 threads for dynamical.org (4 gave no speed-up) |
| `scripts/build_truth.py`, `scripts/download_imd_history.py` | monthly truth; IMD 1991-2023 history |
| `verify/metrics.py` | sufficient-statistic metrics, vectorised for the bootstrap; fair CRPS |
| `verify/bootstrap.py` | paired block bootstrap (5-day blocks), CI and p-value |
| `verify/data.py` | load/pair stores; drops valid days >= 2026-01-01 unless `allow_test` |
| `blend/baselines.py` | equal mean, rolling-origin ridge superensemble, persistence, climatology |
| `verify/scoreboard.py` | stratified scoreboard, common-sample scoring, reliability, skill table |
| `scripts/run_verification.py` | one command for all tables/figures in `reports/phase2/` |

Tests: **104 passed** (1 live deselected); ruff clean. Includes the superensemble leakage test (target-month
observations changed → target-month predictions unchanged) and a bootstrap null-rate check (≤ 15 % of 60
equal-skill trials flagged).

### Incidents and decisions
- **Open-Meteo daily limit hit at ~14:00 UTC** ("Daily API request limit exceeded"). Today's probes, week
  builds and the archiver all counted against it; our ledger only started recording at the backfill.
  Consequences: the archiver's 15:30/21:30 UTC runs today will fail and back-fill tomorrow (lookback 2
  cycles; Single Runs keeps ~180 days, so nothing is lost). The backfill now sleeps until 00:10 UTC on a
  daily-limit 429 instead of polling.
- **Headline scores were not comparable** in the first scoreboard draft (each forecast was scored on its
  own cases; in January 2024 GFS had 31 inits, ICON/GEM 12). Fixed: every table is scored on a common
  sample. Samples: `main` (valid days from 2024-04-01, all but AIFS-ENS), `late` (from 2025-07-02, all).
  Forecasts with < 50 % of the best coverage are left out and listed; paired diffs also use common cases.
- Previous Runs coverage (backfill): IFS HRES has no data in Jan 2024 (prototype showed "usable from
  2024-03"); ICON and GEM start 2024-01-20.
- Superensemble = ridge (λ = 1 on standardised inputs), per lead, pooled over cells, refit monthly on an
  expanding window, ≥ 90 training days; a case needs all selected sources.
- Climatology baseline and Brier skill need all 30 years of the IMD 1991–2020 normal; with a partial normal
  they are omitted, not approximated. IMD history download is running; Tmax 2000 failed once (retry later).
- Regime stratification waits for Phase 4 labels (`regime = "all"` in the skill table).

### Background jobs (started 2026-09-30 ~14:00 UTC)
- dynamical.org backfill (6 adapters x 2 regions x 2024-01..2025-12); GEFS ~36 s/init dominates.
- Previous Runs backfill (3 models x 2 regions); estimated ~10–12 days at 8,000 units/day minus the archiver.
- IMD history download 1991-2023 (Tmax, then rain ~25 MB/yr).
- Archiver scheduler (since 12:40 UTC).
These are processes of this session; if the session or machine stops, rerun the same commands (all resume).

---

## 2026-09-30 (late): Phases 3-7 code done; frontend started; STOPPED at usage limit

Done (committed f545a26 + this commit): Phase 3-5 layers (QM, leak-free tracker, blender A,
LightGBM gate, regimes, tail map + calibrated classifiers, CQR intervals, defer flag, SHAP explanations),
pipeline with ablation switches, `scripts/run_experiments.py` (pre-registered gate rule), districts,
products writer, FastAPI v1 (contract tests pass), bulletins EN/HI with number validation, CAP 1.2 Draft,
SQLite overrides feeding skill penalties. **Tmax pairing bug found and fixed** (IMD Tmax of day D pairs
with window labelled D+1; verified on real data). 135 tests pass.

Not yet run: `run_experiments.py` / `run_verification.py` on real data. They are waiting for the
backfill, so no Phase 2-5 metrics exist yet and none are claimed.

Remaining:
1. Frontend pages (map, district card, skill, verification, sources, replay). Only `lib/`, `components/`,
   layout and CSS are written; `npm run build` has not been run.
2. `/v1/district/{id}` endpoint; `scripts/run_forecast.py` (live products); `scripts/build_replays.py`
   (Wayanad Jul-2024, Vidarbha heat May-2024, plus a third event).
3. Collect 2026 data (`backfill_canonical.py --collect-test`, `build_truth.py --allow-test`). IMD 2026 is
   still unavailable.
4. Run the experiments, write the Phase 2/5 reports, then Phase 8 (frozen test once, README, deploy configs,
   demo dry-runs).

Background jobs (this session only): dynamical fast-source backfill, GEFS backfill, Previous Runs backfill
(sleeping until 00:10 UTC for the Open-Meteo daily quota), archiver scheduler.

---

## 2026-09-30 (evening): scheduling, dashboard, live/replay/final-test scripts

User: "do it" (approval for Windows Task Scheduler; continue).

### Operations
- `scripts/ops/run_job.cmd` + `register_tasks.ps1` register `\TRUSTCAST\` tasks (current user, run while logged
  on, start-when-available, IgnoreNew): archive 03/09/15/21 IST; backfill_prev 05:45; backfill_dyn 06:00;
  backfill_gefs 06:05; truth 12:00; forecast 14:30; weekly (Sun 02:00: verification, experiments, replays).
  Session-bound background jobs stopped; backfills restarted under Task Scheduler.
- `trustcast.io.single_instance` (OS file lock, auto-released on crash) on archiver, backfills and forecast;
  verified: a second process is blocked while the lock is held, acquires after release.
- Backfill: `--exit-on-daily-quota` (scheduled runs stop instead of sleeping), `--collect-test`,
  `--refresh-current`. Truth: `--refresh-current` (current + previous month; IMERG-filled days change).
- Truth for 2026 built (IMERG provisional; IMD 2026 still unavailable).

### Dashboard (Next.js 16.3.7, React 19.2, MapLibre 6.11, Recharts 3.10)
Pages: forecast map (layers, lead, run picker, alert list), district card (chart with 90 % band and
P(>=64.5), weight breakdown, explanations, EN/HI bulletin with number check, CAP link, override form),
who-to-trust (categorical skill map, leaderboard with CI), verification, sources, replay.
`npm run build` OK; `tsc` OK; ESLint clean (fixed React 19 set-state-in-effect and ref-in-render errors).
**Bug found in the dry run**: MapLibre v6 loads its worker as a separate ES module that Turbopack does not
emit ("non-JavaScript MIME type"); fixed by copying worker + shared chunk to `public/maplibre/`
(postinstall) and `setWorkerUrl`.

### Demo dry-run 1 (functional, 2026-09-30 ~16:30 UTC)
API + web via the browser pane (pane hidden, so no screenshots and the map cannot render: the page is
`visibilityState=hidden`). Checked by page text/console: district card (Wayanad) complete, bulletin
validated, replay page, sources page (GEM stale, NCUM not configured), skill map (AIFS lowest recent error
in 70 % of rain-pilot cells for run 2025-02-28), verification page. Leaderboard shows its error state
(no scoreboard yet). Products used were for the newest *development* init available (2025-02-28), not
today: 2026 collection had not caught up. **Visual map check still to do with the pane visible.**

### Replay (real data, partial sources)
Wayanad 2024-07-30: IMD district mean 121.7 mm. Lead-1 forecasts: AIFS 79.0, IFS-ENS mean 38.2,
equal mean 39.5, IFS control 24.0, GFS 16.9, **TRUSTCAST 33.5 mm**. The learned extreme layer starts at
2024-10 so it was not active; the decayed-skill blend smoothed the extreme. IFS HRES, ICON, GEM, GEFS
were not yet backfilled for July 2024. Reported as is.

### Phase 8 runner
`scripts/run_final_test.py`: refuses a second run (FINAL_LOCK.json with git commit, model_selection hash,
coverage); requires model_selection.yaml, >= 80 % test-period coverage per source, and IMD 2026 or an
explicit, recorded `--allow-provisional-truth`. Splits results at the ECMWF change: IFS Cy50r1 + AIFS v2
operational from the 06 UTC run of 2026-05-12 (ECMWF news/forum), i.e. first 00Z init 2026-05-13.
Dry run today: blocked (no 2026 forecasts collected yet, no model_selection.yaml, IMD 2026 0 %).

### Packaging
README (architecture diagram, commands, limitations, attribution), docs/DEMO.md, Dockerfile (API),
web/Dockerfile, docker-compose.yml, web/.env.example.

## 2026-09-30 (night): refinements from first real results
- **IMD real-time tier** for 2026 truth (`truth/imd.py`: rain 0.25°, Tmax 0.5° with one-ring coastal fill
  + bilinear to 0.25°); `truth_v1` gains `rain_source`/`tmax_source` (0 none, 1 IMD final, 2 IMD
  real-time, 3 IMERG). Polite downloader (3 s pause), `scripts/download_imd_realtime.py`.
- **Phase 2 scoreboard, first real run** (reports/phase2, committed 93864ed): rain, the equal-weight mean
  is hard to beat (rain-pilot lead-1 RMSE 11.11; AIFS 11.14); heavy-rain frequency bias 0.3-0.6 for all
  models; IFS-ENS best Brier skill. Tmax in Kerala: raw models (RMSE 2.6-3.2 °C) worse than climatology
  (1.46) and persistence (0.91).
- That evidence led to an **L1 variant: per-cell, leak-free decayed bias removal** for temperature
  (`bias/decayed.py`, built on `skill.tracker.decayed_bias`; leakage test). The L1 variant (qm,
  cell_bias, qm+cell_bias) is chosen on the tune window and gated on the holdout like any layer.
- Regime strata in scoreboards (Phase 5 holdout, Phase 8). Replay districts must have >= 3 cells and >= 50 %
  coverage (Mahe, a one-cell enclave, had been picked).

## 2026-10-01: Phases 3-5 on the dev split, frozen source set, L5 gates

### Incidents
- Scheduled jobs and the experiment run died with 0xC000013A (console Ctrl-C/close) when their console
  windows were closed. Tasks now start through `scripts/ops/run_hidden.vbs` (wscript, no window);
  re-registered and restarted. Long runs I start use detached hidden processes.
- **Dashboard visual check (pane visible)**: CARTO raster tiles now return an "API key required" tile.
  Replaced by keyless OpenFreeMap vector styles (positron/dark); data layers sit under the labels and
  survive the theme switch (style swap with `transformStyle`). Verified light and dark by screenshot.

### Decisions (made before the frozen test; logged here because they shape it)
1. **Frozen source set.** Previous Runs (IFS HRES, ICON, GEM) cover 3 of 24 dev months and GEFS 4 of 24:
   the Open-Meteo daily quota allows ~1 model-region-month per day (~10 more days for dev alone) and GEFS
   reads at ~47 min per month-region. Rather than partially using them, a data-driven rule
   (`verify/assemble.py::source_coverage`): a source is used only if it has >= 80 % of daily 00Z dev
   inits (2024-04-01..2025-12-26, counted from its own first init) over >= 150 days. Result for both
   regions: IFS-ENS control, AIFS, GFS, IFS-ENS, AIFS-ENS (from 2025-07-02). The set is written to
   `model_selection.yaml` and used by forecasts, replays and the frozen test; the other backfills keep
   running for future work but are not used.
2. **Rule 5 applied strictly to Blender A.** Previously a failed A still shipped. Now a failed A is
   disabled (p = 0: equal weights over available sources) and B is gated against the previous *shipped*
   layer. Explanations then say the sources are weighted equally.
3. **L5 gated on its purpose.** The plan asks for event skill next to RMSE for the extreme layer; an RMSE
   gate would always reject sharpening. Split into L5a tail mapping (ships if heavy-event ETS at the first
   threshold is significantly higher at >= 3 of 5 leads and lower at none; paired block bootstrap per
   lead, `verify/compare.py::event_verdict`) and L5b classifiers (ship if Brier at the first threshold is
   significantly lower than the ensemble exceedance fraction, else climatology, and higher than none;
   otherwise probabilities = raw ensemble fraction). **Disclosure:** this gate was written after seeing
   the rain-pilot ablation (tail map: RMSE +0.9 mm, ETS 0.16 -> 0.27) of an earlier run; it is stricter
   than before (previously L5 shipped unconditionally) and it disabled layers in 3 of 8 cases.

### Results (holdout = 2025, tune = 2024-04..12; reports/phase3-5; runtime ~55 min)
| Region · var | L1 | A | B | L5a tail | L5b classifiers |
|---|---|---|---|---|---|
| rain_pilot precip | qm: no (0/5) | no (2/5) | **yes** (3/5 vs equal mean) | **yes** (5/5, ΔETS +0.11) | no (ensemble fraction) |
| rain_pilot tmax | **cell bias yes** (5/5, -1.56 °C) | **yes** (5/5) | **yes** (5/5) | n/a (no ≥ 40 °C days) | **yes** |
| heat_pilot precip | qm: no (worse 5/5) | no (1/5) | no | **yes** (4/5, ΔETS +0.05) | no (ensemble fraction) |
| heat_pilot tmax | **cell bias yes** (5/5, -0.69 °C) | **yes** (4/5) | no (worse 3/5) | no (worse 5/5) | **yes** |

Final product vs baselines (holdout, lead 1; 95 % CI in reports/phase5):
- Rain pilot Tmax: TRUSTCAST RMSE 0.94 °C [0.89, 0.98] vs equal mean 2.74, superensemble 1.77,
  climatology 1.41. Heat pilot Tmax: 0.88 [0.82, 0.95] vs 1.73 / 1.25 / 2.44; heat-day ETS 0.64 vs 0.43.
- Rain: **TRUSTCAST has higher RMSE than the equal mean** (rain pilot 10.90 vs 10.31 mm at lead 1;
  heat pilot 8.52 vs 8.02) because the tail mapping restores heavy-rain amounts; in exchange heavy-rain
  ETS 0.29 vs 0.23 and frequency bias 0.99 vs 0.54 (rain pilot, lead 1). Not hidden: this is the plan's
  trade-off, shown in every table.
- CQR 90 % intervals (holdout coverage by lead): rain 93.6-95.5 % (conservative: too wide), Tmax
  89.4-90.5 %.
- Defer flag (rain pilot precip): 17.5 % of cases flagged; their RMSE is 2.9x that of unflagged cases.
- Ablations (lead 1 RMSE): removing AI sources hurts everywhere (rain pilot rain 11.34 vs 10.90, heat pilot
  rain 8.89 vs 8.52, Tmax 1.16 vs 0.94 and 0.94 vs 0.88); removing bias correction doubles Tmax error
  (2.11 vs 0.94, 1.62 vs 0.88); regime features change little (< 0.01 mm / °C).
