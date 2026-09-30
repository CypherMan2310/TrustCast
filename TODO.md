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

## Phase 2: Baselines and verification harness
- [x] Harness, baselines, bootstrap, common-sample scoreboard, skill table, one command (tests green).
- [x] IMD 1991-2023 history on disk (climatology baseline + BSS reference).
- [ ] Dev backfill complete (dyn fast sources ~hours; GEFS ~1-2 days; Previous Runs ~10-12 days of quota).
- [ ] Scoreboard on complete dev data (weekly job re-runs it automatically).

## Phase 3-5
- [x] QM, leak-free tracker (leakage test), blender A, gate B, regimes, tail map, calibrated classifiers,
      CQR, defer flag, SHAP explanations, pipeline + ablations, experiment driver (tests green).
- [ ] `run_experiments.py` on complete dev data -> reports/phase3-5, config/model_selection.yaml.

## Phase 6
- [x] API contract + implementation (6 contract tests), products writer, districts.
- [x] Dashboard: map, district card, skill, verification, sources, replay; build + ESLint clean.
- [ ] Live products for today's runs (needs 2026 collection; daily `forecast` task).

## Phase 7
- [x] Replays (Wayanad 2024 built on partial data), EN/HI bulletins with number validation, overrides
      feeding skill state, CAP 1.2 Draft export.
- [ ] Replays rebuilt on complete data (weekly task).

## Phase 8
- [x] Frozen-test runner with run-once lock and ECMWF-change split; README; Docker; demo script.
- [ ] Preconditions: 2026 data collected, model_selection.yaml from dev, IMD 2026 (or recorded provisional).
- [ ] Run the frozen test once; lock numbers in WORK.md.
- [ ] Two demo dry-runs logged.
