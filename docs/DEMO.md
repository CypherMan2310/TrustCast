# Demo script (about 4 minutes)

> Decision-support tool. Not an official warning. Every number shown is computed from real data by the
> pipeline; say "provisional" wherever the page says so.

Setup (before the audience arrives): API on :8000 (`uvicorn trustcast.api.app:app`), web on :3000
(`npm run start` after `npm run build`), latest products present (`GET /v1/health` → status ok).
Fallback: if the network or a source fails, the site still runs from local products; the Sources page
shows which sources are stale or failed (that is part of the story, not a failure).

1. **Forecast map** (`/`). Rain pilot, lead day 1. "One forecast, blended from up to nine models, on the
   IMD 0.25° grid and the 08:30–08:30 IST rain day." Switch the layer to *Model disagreement*, then to
   *P(≥ 64.5 mm)*. Point at the alert list on the right.
2. **Who to trust** (`/skill`). The categorical map: the model with the lowest recent verified error per
   cell. "This changes with region, lead time and season, which is why a fixed ensemble is not enough."
   Show the leaderboard with 95 % intervals.
3. **District card**. Click a district in the alert list. Walk through: blended value and 90 % range,
   heavy-rain probability, the weight breakdown by model, the regime, the plain-language reason.
   Toggle the bulletin to Hindi; point out "every number checked against the forecast". Open the CAP XML
   (status Draft, restricted to forecaster review).
4. **Replay** (`/replay`). Wayanad, 30 July 2024: what each model said 1–5 days ahead vs IMD. Be honest:
   the blend under-forecast this extreme; AI (AIFS) was closest; this is the case the extreme layer and
   the gate address, and why every layer has to earn its place on held-out data.
5. **Graceful degradation**. Sources page: GEM is stale (provider stopped on 2026-05-26), NCUM is "not
   configured". The blend simply drops them and renormalises; nothing is substituted.
6. **Forecaster override**. On a district card, distrust one model with a reason and save. "The next
   runs down-weight that model in this district for about a week." Show the bulletin now mentions the
   override.
7. **Verification** (`/verification`). Layer decisions (ships / disabled) with the pre-registered rule,
   and the frozen-test status.

Dry-run log: append date, duration, and anything that went wrong to `WORK.md` ("Demo dry-runs").
