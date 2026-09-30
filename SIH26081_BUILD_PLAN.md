# SIH26081 — Hybrid AI–NWP Multi-Model Forecast Blending System
## Build Plan (data → models → verification → product → demo)

**Working title:** TRUSTCAST (rename freely)
**Sponsor / theme:** NCMRWF, Ministry of Earth Sciences · Disaster Management · Software
**One-line pitch:** *A system that learns, from real verification against IMD observations, which weather model to trust for every place, season, lead time and weather regime, blends them into one calibrated forecast that does not smooth away extremes, and explains its decision to the forecaster.*

> Verify the official problem-statement text on sih.gov.in before finalising scope. This plan is reconstructed from public team write-ups, and one aggregator lists a different title for this ID.

---

## 1. Reality checks (read first)

| # | Fact | Consequence |
|---|------|-------------|
| 1 | Idea submission was listed as closing **30 Sep 2026**. | If not yet submitted, do the PPT (Section 11) before anything else. Confirm on the portal. |
| 2 | **Archived forecast runs are short.** Open-Meteo's lead-time-stratified "Previous Runs" start Jan 2024; its single-run archive starts Mar 2024 for IFS and Sep 2025 for other models; dynamical.org's IFS ENS starts Apr 2024. | Your honest training history is roughly **2024–2026 (about 2.5 years)**. Design for it: online/decayed weighting, few parameters, strict out-of-time test. |
| 3 | **NCUM / NEPS (NCMRWF's own models) are not public.** | Build a **source adapter interface**. Use IFS/GFS/ICON/GEM/GEFS/AIFS now. Check whether the PS page's dataset link provides NCMRWF fields. If it does, plug them in as extra sources. |
| 4 | **Many teams are on this PS.** Public repos already do BMA, LightGBM gating, U-Net, MoE, dashboards. Several use synthetic data. | Win on **credibility and operational thinking**, not on a fancier network. |
| 5 | IMD gridded **temperature is 1°** (rain is 0.25°). | Heat verification is coarse. Say so, and use station data for the heat pilot if you can get it. |
| 6 | ECMWF IFS moved to a new cycle in May 2026. | Model behaviour changes. Add a drift monitor and report skill before/after. |

---

## 2. Architecture

```
 SOURCES (adapters)                     CORE                                   PRODUCT
 ┌───────────────────┐   ┌────────────────────────────────────┐   ┌─────────────────────────┐
 │ NWP: IFS, GFS,    │   │ 1 Ingest → common Zarr schema      │   │ FastAPI                 │
 │  ICON, GEM        │──▶│ 2 Regrid + align (init, lead)      │──▶│  /blend /skill /alerts  │
 │ AI: AIFS Single   │   │ 3 Bias-correct (quantile mapping)  │   │  /bulletin /replay      │
 │ ENS: GEFS, IFS-ENS│   │ 4 Skill tracker (leak-free)        │   ├─────────────────────────┤
 │ AIFS-ENS          │   │ 5 Blenders: A decayed-skill        │   │ Next.js + MapLibre      │
 │ (NCUM/NEPS later) │   │            B LightGBM gate         │   │  skill map, district    │
 ├───────────────────┤   │ 6 Extreme-event layer (tails)      │   │  card, replay, override │
 │ TRUTH: IMD grid,  │   │ 7 Uncertainty (CQR + conformal)    │   ├─────────────────────────┤
 │ IMERG, ERA5       │──▶│ 8 Defer flag + explainability      │   │ Alerts: bulletin, CAP,  │
 └───────────────────┘   │ 9 Verification harness             │   │ Telegram/email          │
                         └────────────────────────────────────┘   └─────────────────────────┘
```

**Stack (all free-tier friendly):** Python 3.12, xarray, zarr, dask, numpy, pandas, scikit-learn, LightGBM, MAPIE or own conformal code, SHAP, DuckDB + Parquet for skill tables, FastAPI, Next.js, MapLibre GL, ECharts/Recharts. Deploy the backend on Hugging Face Spaces or Render and the frontend on Vercel. Schedule runs with GitHub Actions cron or APScheduler.

---

## 3. Data sources — where to get the data

**"Scraping" note:** almost everything you need is available through an API, bulk download or open bucket. Use those. Only fall back to scraping for pages with no API (IMD warning pages), and then: read the site's terms and robots.txt, cache aggressively, at most one request every few seconds, and never scrape behind a login.

### 3A. Forecast sources (the models being blended)

| Source | What | How to access | Depth / notes |
|---|---|---|---|
| **Open-Meteo** (api.open-meteo.com) | 30+ models incl. ECMWF IFS, NOAA GFS, DWD ICON, GEM; free JSON | HTTP GET, no key | Free for **non-commercial** use, CC BY 4.0. Live forecasts. |
| Open-Meteo **Historical Forecast API** | Archived seamless forecasts | HTTP GET | From 2021. Not lead-stratified. Good for quick prototypes. |
| Open-Meteo **Previous Runs API** | Forecast at a fixed 1–7 day lead | HTTP GET | From Jan 2024. **Your main source for lead-time-stratified training.** |
| Open-Meteo **Single Runs API** | Full horizon of one run by init time | HTTP GET | IFS from Mar 2024; other models from Sep 2025. Use for backtests without look-ahead. |
| **dynamical.org catalog** (`pip install dynamical-catalog`, Python 3.12+) | GEFS (31 members), IFS ENS (51 members), **AIFS Single**, AIFS ENS as Zarr | `dynamical_catalog.open("<id>")`, anonymous; also public S3 buckets `--no-sign-request` | CC BY 4.0. **Check each dataset's init_time range** in its docs. AIFS Single and AIFS ENS update every 6 h. |
| **ECMWF Open Data** (data.ecmwf.int, also mirrored on AWS/Google/Azure) | IFS and AIFS open forecasts (GRIB2) | `ecmwf-opendata` Python client or bucket | Use as a fallback and for fields Open-Meteo lacks. |
| **NOAA GFS / GEFS** on AWS Open Data | GRIB2 | `s3://noaa-gfs-bdp-pds`, `noaa-gefs-pds` (no-sign-request) | Deep archive. Good for extending GFS history beyond Open-Meteo. |
| **DWD ICON** (opendata.dwd.de) | ICON global GRIB2 | HTTP download | Recent runs only; archive yourself going forward. |
| **NCMRWF NCUM / NEPS** | India's own deterministic + ensemble models | Via the PS dataset link or an NCMRWF request | Not public. Keep the adapter slot ready. |
| **Your own daily archiver** | Snapshot every source at each 00/12Z run | Scheduled job → Zarr | **Start this on day 1.** Every day of your own lead-stratified archive is training data no competitor has. |

*AI models:* use archived **AIFS** (open). Do **not** try to run GraphCast/Pangu inference yourself for the MVP. Add them only if a free archive exists.

### 3B. Ground truth (what you verify against)

| Source | Variable | Access | Notes |
|---|---|---|---|
| **IMD gridded rainfall** (imdpune.gov.in → Gridded data) | Daily rain, 0.25°, 1901–present | `pip install imdlib` → `imd.get_data('rain', y0, y1)` | Primary rain truth. Expect a reporting lag; handle missing values (`< -100` are missing). |
| **IMD gridded Tmax/Tmin** | Daily, **1.0°** | `imdlib` (`'tmax'`, `'tmin'`) | Coarse. State this limitation. |
| **NASA GPM IMERG** (GES DISC / Earthdata, free login) | Satellite rain, 0.1°, near-real-time (Early/Late/Final) | Earthdata download / `earthaccess` | Fills the IMD lag; use for recent-day verification. |
| **CHIRPS** (data.chc.ucsb.edu) | Rain, 0.05° | HTTP download | Secondary check. |
| **ERA5 / ERA5-Land** (Copernicus CDS) | Reanalysis fields | `cdsapi` with a free key | Regime features and consistency checks; not the primary truth. |
| **NCMRWF IMDAA / MERA** | Regional reanalysis / rainfall analysis | NCMRWF data portal (DOIs are cited in public repos) | Nice credibility touch for a sponsor that produced them. |
| **IMD station/city data** (mausam.imd.gov.in) | Station obs, warnings | Website pages/PDFs | Only where no API exists; scrape politely. |

### 3C. Static / geographic

| Source | Use | Access |
|---|---|---|
| LGD district boundaries (lgdirectory.gov.in) or DataMeet India maps (GitHub) | District aggregation, alerts | Download shapefile/GeoJSON |
| IMD meteorological subdivision polygons | Skill maps at the operational unit IMD uses | DataMeet / IMD |
| Copernicus DEM GLO-90, Natural Earth coastline | Terrain slope, windward index, distance to coast (gating features) | Direct download |

### 3D. Events, alerts, context

| Source | Use |
|---|---|
| IMD daily warnings and cyclone bulletins (mausam.imd.gov.in) | Event catalogue; compare your alerts vs IMD's |
| NDMA **SACHET** (sachet.ndma.gov.in) | CAP alert format and live alert feed, for interoperability |
| India-WRIS, CWC flood bulletins | Impact context for flood events |
| GDACS, EM-DAT (free registration) | Event verification catalogue |
| BoM **RMM (MJO) index** | Optional regime feature |

> Confirm every URL and access method before coding it; portals move. Record what you actually used in `DATA_SOURCES.md` with access date and licence.

---

## 4. Data layer build

1. **Adapters:** one class per source with `fetch(init_time, bbox) -> xr.Dataset` in the shared schema. Adding NCUM later means adding one adapter.
2. **Schema:** dims `(init_time, lead_h, lat, lon)`, per-source variables `precip_24h_mm`, `tmax_c` (extend later to `wind_gust`, `mslp`). Attributes: source, model version, licence, fetch time.
3. **Regrid** everything to the IMD 0.25° grid (conservative regridding for rain, bilinear for temperature, elevation-corrected for Tmax).
4. **Storage:** `data/raw/` (as fetched, immutable) → `data/processed/*.zarr` → `data/skill/*.parquet` (DuckDB queries). Every file has a manifest (source, hash, time).
5. **Truth alignment:** IMD daily rain is 08:30 IST to 08:30 IST. Align forecast accumulation windows to it exactly. This is a common source of quiet errors.
6. **Splits (freeze before modelling):**
   - Development: Jan 2024 – Dec 2025, with rolling-origin cross-validation.
   - **Held-out test: Jan – Sep 2026** (includes the 2026 monsoon and heat season). Do not tune on it.
7. **Pilot region:** one rain-dominated and one heat-dominated set of subdivisions. Choose by data quality and by avoiding regions other teams already chose. Design for national scale.

---

## 5. Model build

Build in this order. Each layer must beat the previous one on the dev split or it does not ship.

**L0 — Baselines (benchmarks to beat):** each single source; equal-weight mean; static multi-model ensemble (regression-weighted superensemble); climatology; persistence.

**L1 — Bias correction:** per source, per cell (or subdivision), per lead-bucket, per season. Rain: empirical/gamma quantile mapping. Temperature: quantile mapping with lapse-rate correction. Fit on training data only.

**L2 — Skill tracker (leak-free):** for a forecast issued at time *t*, use only verification whose valid time ≤ *t*. Keep exponentially decayed error (RMSE, MAE) and event scores per (cell, lead, season). Half-life is a tunable (start with 15–30 days).

**L3A — Adaptive blender A:** weights ∝ 1 / decayed-MSE^p per cell × lead, normalised. This is the interpretable baseline that must work end-to-end first.

**L3B — Gated blender B:** LightGBM predicts each source's expected absolute error from: consensus value, ensemble spread, inter-model disagreement, each source's recent skill, lead, season (sin/cos day-of-year), terrain features, and a regime label. Convert predicted errors to weights with a softmax and a temperature tuned on validation. Keep the model small (shallow trees, strong regularisation). Data is limited.

**L4 — Regime awareness:** start rule-based (monsoon active/break from consensus rainfall pattern; heat-wave/cyclone flags from thresholds), and optionally add the MJO/RMM index. Regime is a gating feature *and* a label shown to the forecaster.

**L5 — Extreme-event layer (your differentiator):**
- Tail-preserving mapping so blended output matches the observed rain distribution at high quantiles.
- Separate LightGBM classifiers for P(≥ 64.5 mm) and P(≥ 115.6 mm) (IMD heavy / very heavy rain categories), trained with class weights.
- Report ETS/CSI, POD, FAR and frequency bias for those thresholds next to RMSE. Show the trade-off honestly.

**L6 — Uncertainty:** LightGBM quantile models (q05–q95) plus split-conformal calibration on a rolling window (CQR). Validate with reliability diagrams and coverage checks. Output exceedance probabilities.

**L7 — Defer flag and explainability:** flag "low confidence, forecaster review" when disagreement is high and predicted skill is low. Explain each district with the weight breakdown, top gating features (SHAP), the regime label and a plain-language sentence.

**L8 — Graceful degradation:** if a source is missing at run time, drop it and re-normalise weights. Test this explicitly.

---

## 6. Verification protocol (this is what you win on)

- **Metrics:** RMSE, MAE, bias; CRPS (probabilistic); Brier skill score and reliability for exceedances; ETS/CSI, POD, FAR, frequency bias for heavy-rain thresholds; heat-day hit rates.
- **Stratify by:** region, lead day (1–5+), season, regime.
- **Statistics:** paired block bootstrap (5-day blocks, 95% intervals). Report where the blend is *not* significantly better. Honest nulls build trust.
- **Ablations:** remove AI sources; remove bias correction; remove the gate (A only); remove the extreme layer; remove regime features.
- **Out-of-time test:** Jan–Sep 2026, run once, frozen. Also report before/after the IFS cycle change.
- **Replay case studies** (all inside the archive window): Wayanad landslides (Jul 2024), Cyclone Remal (May 2024), Cyclone Dana (Oct 2024), Cyclone Fengal (Nov–Dec 2024), the 2024 heatwave season. Show what each single model said vs the blend, days ahead.
- **Reproducibility:** one command reruns verification and regenerates every figure in the deck.

---

## 7. Product features

**Must:** live blended forecast map and district cards; probability of exceeding IMD thresholds; **"who to trust" skill map and leaderboard** by region/lead/season; model-disagreement map; verification page (live scoreboard); REST API + OpenAPI docs.

**Should:** explain-this-forecast card; regime label; low-confidence flag; replay mode for real events; forecaster override with reason, fed back into skill tracking; auto-generated impact bulletin (template-first, deterministic; optional LLM polish strictly grounded on numbers; English + one regional language); CAP-format alert export.

**Stretch:** wind gust and cyclone track blending; MJO regime feature; district SMS/Telegram alerts; mobile-friendly view; "what changed since the last run" diff view; NCUM/NEPS adapter demo using any sample data provided.

**Guardrail copy everywhere:** "Decision-support tool. Not an official warning."

---

## 8. Roadmap (compress or stretch to your finals date)

| Phase | Goal | Gate to pass |
|---|---|---|
| **0** | Idea PPT submitted; repo + CLAUDE/TODO/WORK files; **daily archiver running** | Submission done; archiver writes a real Zarr |
| **1** | Adapters for Open-Meteo, dynamical.org, IMD truth; common schema; manifests | One real week aligned end to end, no synthetic data |
| **2** | Baselines + verification harness (metrics, bootstrap) | Baseline scoreboard reproducible with one command |
| **3** | L1 bias correction + L2 skill tracker + L3A blender | Beats equal mean on dev split, or you understand why not |
| **4** | L3B gate + regime + L8 degradation | Improves on L3A in bootstrap, or is dropped |
| **5** | L5 extremes + L6 uncertainty + L7 flags | Calibration plots pass; heavy-rain ETS reported |
| **6** | API + frontend (map, skill map, district card, verification page) | Demo flows work on live data |
| **7** | Replay cases, bulletins, override loop, CAP export | 3 replay events rehearsed |
| **8** | Frozen test run, deck, demo video, README, rehearsals | Final numbers locked; two dry-runs completed |

---

## 9. Repo layout

```
trustcast/
  CLAUDE.md  TODO.md  WORK.md  DATA_SOURCES.md  README.md
  data/{raw,processed,skill}/
  src/
    adapters/      # one file per source
    grid/          # regrid, align, schema
    bias/          # quantile mapping
    skill/         # tracker, leak-free
    blend/         # baselines, decayed, gated
    extremes/      # tail mapping, threshold classifiers
    uncertainty/   # quantile + conformal
    verify/        # metrics, bootstrap, ablations, plots
    api/           # FastAPI
    alerts/        # bulletin, CAP, notifiers
  web/             # Next.js + MapLibre
  tests/  notebooks/  scripts/
```

---

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Short archive → overfit | Few parameters, decayed weights, frozen out-of-time test, report intervals |
| Blend smooths extremes | L5 layer, event-based metrics beside RMSE |
| Look-ahead leakage | Unit test: the skill tracker never reads data with valid time after issue time |
| Source outage during demo | Cached last-good run, graceful degradation, recorded fallback demo |
| IMD data lag | Use IMERG for recent days; label provisional verification |
| Free API throttling | Cache, batch by bbox, archive locally, respect fair use |
| Scope creep | Ship phases 0–6 fully before any stretch item |
| Honesty gap (synthetic data in demo) | Synthetic data allowed **only in unit tests**, and never displayed as real |

---

## 11. Idea PPT and demo storyline

**PPT (concise):** problem → why static ensembles fail (different models win in different places, seasons, regimes) → approach (adapt, protect extremes, quantify uncertainty, explain) → architecture → data sources (all real, open) → verification design → feature list → impact for NCMRWF/IMD forecasters → roadmap.

**Finals demo (about 4 min):**
1. Open the skill map: "here is who to trust today, by region and lead."
2. Click a district: blended forecast, exceedance probability, weight breakdown, regime.
3. Replay a real disaster (e.g. Wayanad 2024): single models vs blend, days ahead.
4. Verification page: real numbers, confidence intervals, honest limitations.
5. Kill a data source live: the system degrades gracefully.
6. Forecaster override → bulletin export.

---

## 12. Working agreement (applies to the whole build)

- `CLAUDE.md` holds the strict rules, full architecture and tech stack, so no model hallucinates structure.
- `TODO.md` lists work per module touched.
- `WORK.md` logs tasks actually completed, with dates and test results.
- Update all three at the end of every module. No exceptions.
