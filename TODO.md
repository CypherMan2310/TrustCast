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
- [ ] Scheduler actually running (local task or GitHub remote). **Needs user decision** (see WORK.md open questions).

## Phase 1: Adapters and truth (not started)
- [ ] `SourceAdapter.fetch(init_time, bbox) -> canonical_v1` for Open-Meteo (live, Previous Runs, Single Runs).
- [ ] dynamical.org adapters: AIFS Single, GEFS, IFS-ENS, AIFS-ENS.
- [ ] ECMWF/NOAA bucket fallback adapter.
- [ ] `NcumAdapter` stub raising `NotConfigured`.
- [ ] IMD truth loader (rain 0.25°, Tmax 1.0°) via imdlib; IMERG (dynamical.org) for recent days, `provisional`.
- [ ] Regridding + 08:30 IST window alignment with hand-checked unit tests (incl. AIFS 6 h steps).
- [ ] Check: one real week, pilot region, all sources aligned on the IMD grid; missing-value handling documented.
