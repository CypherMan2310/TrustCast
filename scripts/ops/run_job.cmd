@echo off
REM TRUSTCAST scheduled job runner (Windows Task Scheduler). Usage: run_job.cmd <job>
REM Every job is resumable and single-instance (file locks); output is appended to data\logs\task_<job>.log
setlocal
cd /d "%~dp0..\.."
set PY=.venv\Scripts\python.exe
set LOG=data\logs\task_%1.log
if not exist data\logs mkdir data\logs
echo ==== %date% %time% start %1 >> %LOG%
if "%1"=="archive" %PY% scripts\archive_run.py >> %LOG% 2>&1
if "%1"=="backfill_prev" (
  %PY% scripts\backfill_canonical.py --kind prev --exit-on-daily-quota >> %LOG% 2>&1
  %PY% scripts\backfill_canonical.py --kind prev --collect-test --start 2026-01 --end 2026-12 --refresh-current --exit-on-daily-quota >> %LOG% 2>&1
)
if "%1"=="backfill_dyn" (
  %PY% scripts\backfill_canonical.py --kind dyn --adapters ifsctrl_dyn aifs_dyn gfs_dyn ifsens_dyn aifsens_dyn >> %LOG% 2>&1
  %PY% scripts\backfill_canonical.py --kind dyn --adapters ifsctrl_dyn aifs_dyn gfs_dyn ifsens_dyn aifsens_dyn --collect-test --start 2026-01 --end 2026-12 --refresh-current >> %LOG% 2>&1
)
if "%1"=="backfill_gefs" (
  %PY% scripts\backfill_canonical.py --kind dyn --adapters gefs_dyn >> %LOG% 2>&1
  %PY% scripts\backfill_canonical.py --kind dyn --adapters gefs_dyn --collect-test --start 2026-01 --end 2026-12 --refresh-current >> %LOG% 2>&1
)
if "%1"=="truth" (
  %PY% scripts\download_imd_history.py --start 2026 --end 2026 >> %LOG% 2>&1
  %PY% scripts\build_truth.py --start 2024-01 --end 2025-12 >> %LOG% 2>&1
  %PY% scripts\build_truth.py --start 2026-01 --end 2026-12 --allow-test --refresh-current >> %LOG% 2>&1
)
if "%1"=="forecast" %PY% scripts\run_forecast.py >> %LOG% 2>&1
if "%1"=="weekly" (
  %PY% scripts\run_verification.py >> %LOG% 2>&1
  %PY% scripts\run_experiments.py >> %LOG% 2>&1
  %PY% scripts\build_replays.py >> %LOG% 2>&1
)
echo ==== %date% %time% end %1 (exit %errorlevel%) >> %LOG%
endlocal
