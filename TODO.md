# TODO.md

Work items per module, each with an acceptance check. Tick only when the check has been run and passed.

## Phase 0: Foundations

### repo / conventions
- [x] Repo skeleton per plan §9 (package under `src/trustcast/`). Check: tree matches CLAUDE.md §4.
- [x] `CLAUDE.md`, `TODO.md`, `WORK.md`, `DATA_SOURCES.md`, `.env.example`, ruff/pytest config.
- [x] Python 3.12 venv + pinned `requirements.txt` / `requirements.lock`. Check: `.venv/Scripts/python -V` = 3.12.
- [x] Pre-Phase-0 prototype moved to `prototype/`, data kept. Check: `prototype/config.py` resolves `data/`.
- [ ] git: initial commit. Check: `git log` shows the Phase 0 commit series.

### grid (contracts)
- [x] IMD 0.25° / 1.0° grid definitions, on-grid bbox subsetting. Check: `tests/test_grid.py` green.
- [x] `archive_hourly_v1` and `canonical_v1` schema validators. Check: schema tests green.

### adapters (Phase 0 part)
- [x] Open-Meteo Single Runs client: metadata, batched multi-point fetch, retries, empty/NaN detection.
      Check: `tests/test_openmeteo_parse.py`, `tests/test_archiver.py` green.
- [x] Rate limiter (400/min blocking, 4000/h non-blocking). Check: `tests/test_ratelimit.py` green.

### archive
- [x] Cycle selection (00/12Z, lookback, staleness). Check: `tests/test_cycles.py` green.
- [x] Raw gzip JSON + Zarr + manifest with SHA-256 digests; `verify_manifest`. Check: tamper tests green.
- [x] Idempotent runner; failures recorded, never substituted. Check: `tests/test_archiver.py` green.
- [x] **One real run** written to `data/raw/` and `data/processed/`, manifests verified.
      Check: `scripts/archive_run.py` exit 0, `scripts/verify_archive.py` all OK. (16/16 verified, 2026-09-30)
- [x] Scheduling: `scripts/scheduler.py` (APScheduler) + `.github/workflows/archive.yml`.
- [x] Scheduler running: `scripts/scheduler.py` background process (non-persistent; revisit Task Scheduler / GitHub Actions).

## Phase 1: Adapters and truth (done 2026-09-30)
- [x] `SourceAdapter.fetch(init_time, bbox) -> canonical_v1` for Open-Meteo Previous Runs, Single Runs, Live.
      Check: `tests/test_adapters.py`, `tests/test_canonical.py`; real week built.
- [x] dynamical.org adapters: AIFS Single, GFS, GEFS, IFS-ENS, AIFS-ENS, IFS control (member 0). Check: real week.
- [x] ECMWF open-data fallback adapter. Check: real 2026-09-30 00Z run, r = 0.9989 vs Single Runs path.
- [x] `NcumAdapter` stub raising `NotConfigured`. Check: `test_ncum_stub_raises_not_configured`.
- [x] IMD truth loader (rain 0.25°, Tmax 1.0°), raw reader equals imdlib; IMERG provisional fill. Check: `tests/test_truth.py`.
- [x] Regridding + 08:30 IST window alignment with hand-checked tests (incl. 6 h straddling steps).
      Check: `tests/test_align.py`, `tests/test_regrid.py`.
- [x] One real week, both pilot regions, all eval sources aligned on the IMD grid; missing-value handling
      documented (WORK.md). Check: `scripts/build_canonical.py` reports for rain_pilot and heat_pilot.
- [ ] **Open:** IMD 2026 rain/Tmax files (needed before Phase 8). Check: `data/truth/{rain,tmax}/2026.*` non-empty.

## Phase 2: Baselines and verification harness (STOP gate), in progress
- [x] Quota-safe bulk backfill (`scripts/backfill_canonical.py`, resumable, cross-process ledger, land cells only).
      Check: real month built (icon_prev heat_pilot 2025-10, 31 inits, 0 missing).
- [ ] **Backfill complete** for 2024-01..2025-12 (both regions): dynamical.org (~hours) and Previous Runs
      (~10–12 days at the free quota). Check: `reports/phase2/coverage.csv`.
- [x] Dev truth, monthly, both regions (`scripts/build_truth.py`). Check: 24 months x 2 regions, 0 provisional.
- [ ] IMD 1991–2020 normal on disk (climatology baseline + BSS reference). Check: `download_imd_history.py` reports no failures.
- [x] Baselines: equal mean, rolling-origin superensemble, persistence, climatology (code). Check: `tests/test_baselines.py`
      incl. superensemble leakage test.
- [x] Metrics (RMSE, MAE, bias, fair CRPS, Brier/BSS, reliability, ETS/CSI/POD/FAR/fbias). Check: `tests/test_verify.py`.
- [x] Paired block bootstrap (5-day blocks), unit-tested on synthetic fixtures incl. a null-rate check.
- [x] Stratification region x lead x season; common-sample scoring; skill table Parquet. Check: `tests/test_scoreboard.py`.
- [ ] Regime stratum (needs Phase 4 regime labels; `regime = "all"` until then).
- [x] One command: `python scripts/run_verification.py` regenerates all tables/figures in `reports/phase2/`.
- [ ] Report the baseline scoreboard to the user, then STOP.
