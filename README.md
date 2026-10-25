# GB Wind Forecast: Day-Ahead Check

A web app for a day-ahead electricity procurement team. For any January 2026 purchase decision it shows:

1. **which wind forecast was available at the decision cutoff** (the latest forecast published before it, never a later one),
2. **how that forecast compared with metered wind generation**, and
3. **the size and direction of the error**.

Data: national Great Britain wind only, from Elexon BMRS (`WINDFOR` forecasts, `FUELHH` actuals).

| | |
|---|---|
| **Live app** | https://gb-wind-forecast-dashboard.vercel.app/ |
| **Stack** | React (Vite, Recharts) · Python FastAPI + pandas · Docker · Vercel |

## AI assistance disclosure

This project was built with substantial help from **Anthropic's Claude** (an AI assistant). Claude was used for:
- researching the Elexon datasets and the forecasting workflow,
- designing the architecture and evaluation method,
- writing the backend, frontend, tests, scripts, Dockerfiles and this README.

The author ran the data-verification and diagnostic scripts against the live Elexon API, ran the unit tests and the end-to-end self-check, and deployed the app. Statements about data behaviour in this README come from those runs; anything not verified is labelled as an assumption.

## What the dashboard shows

- **Decision view:** pick a decision date and cutoff; see the forecast run used (with its publication time), forecast vs actual for the delivery day, and MAE / RMSE / bias / error spread / weighted % error / net MWh.
- **Error analysis:** average error by delivery hour, by day, and by hours-ahead.
- **Forecast evolution:** how the forecast for one delivery hour changed across publications; runs published after the cutoff are greyed out.
- **Data quality panel:** source, row and publication counts, detected resolution, missing values, assumptions.
- **Controls:** decision date, cutoff (09:20 or 09:50 UK time), comparison mode, date range, CSV download.

## Quick start (Windows)

Requires Python 3.9+ and Node 20+.

```
setup.bat        # creates the venv, runs tests, downloads Jan 2026 data, installs the frontend
start_all.bat    # starts backend (:8000) and frontend (:5173)
check_api.bat    # PASS/FAIL checks for every endpoint and the frontend proxy (needs the app running)
check.bat        # unit tests + production frontend build
```

Manual: `cd backend`, `.venv\Scripts\activate`, `python -m pytest -q`, `uvicorn app.main:app --port 8000`; in a second terminal `cd frontend`, `npm install`, `npm run dev`.

Docker: `docker build -t wind .` then `docker run -p 8080:8000 wind` (open http://localhost:8080). The committed `data/snapshot.json` is baked into the image.

## Project structure

```
backend/app/core.py        fetching, normalisation, forecast selection, metrics
backend/app/main.py        FastAPI endpoints (+ serves the built frontend in Docker)
backend/tests/             unit tests for the data logic
backend/smoke_check.py     end-to-end API/frontend self-check
backend/align_check.py     alignment + horizon diagnostics on the snapshot
frontend/src/App.jsx       React dashboard
data/snapshot.json         Elexon data for the pilot (so the app works if the API is slow or down)
verify_elexon.py           script that tests the Elexon API behaviour and saves raw fixtures
Dockerfile                 local Docker
Dockerfile.vercel          container used by the Vercel deployment
heroku.yml                 optional Heroku container deploy
```

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/meta` | data source, counts, detected resolution, assumptions |
| `GET /api/day?decision_date=&cutoff=&align=` | forecast vs actual for one delivery day, with the run used |
| `GET /api/metrics?from=&to=&cutoff=&align=` | metrics for a range, plus by-hour / by-day / by-hours-ahead |
| `GET /api/evolution?start_time=&cutoff=` | all forecast publications for one delivery hour |
| `GET /api/export.csv?from=&to=&cutoff=&align=` | matched table as CSV |
| `POST /api/refresh` | re-fetch from Elexon (in memory only on Vercel's read-only disk) |

## Data sources and verified behaviour

Base URL: `https://data.elexon.co.uk/bmrs/api/v1`. Endpoints: `/datasets/FUELHH/stream` and `/datasets/WINDFOR/stream`. No API key is needed.

Observed by running `verify_elexon.py` against the live API (5–7 Jan 2026 sample) and by building the full-month snapshot:

- **WINDFOR (forecast)** is **hourly** (`startTime` always on the hour), published about **8 times a day at :30 past the hour** (02, 04, 07, 09, 11, 15, 18, 22 UTC in the sample). Each run holds about 73 hourly values. Full snapshot: 276 distinct publication times, 20,148 rows.
- **Historical forecast versions are retrievable** by filtering on `publishDateTimeFrom` / `publishDateTimeTo`.
- **With no filter, WINDFOR returns only the latest run** (today's, not January's). The app therefore always requests a publication-time window.
- **WINDFOR ignores `settlementDateFrom/To`** (returns the same latest-only result), so it is never used for filtering.
- **FUELHH (actuals)** is half-hourly with `publishTime`; for 5–7 Jan there were 144 WIND rows, no duplicates, no conflicting values and no gaps. Full snapshot: 1,536 rows (1 Jan–1 Feb), 0 missing.
- Timestamps are UTC (`Z`). January 2026 is GMT, so UTC equals UK local time and every day has 48 half-hours.
- Forecast times match actuals only on the hour, so the comparison method below is needed.

## Method

**Scope (assumption, unconfirmed):** "decisions made in January 2026" is read as *decision date in January*, giving delivery dates 2 Jan–1 Feb.

**Cutoff (assumption, unconfirmed):** 09:20 Europe/London on the day before delivery (the earlier of the main GB day-ahead auction closures); 09:50 is selectable. A forecast is eligible if `publishTime <= cutoff`. The choice matters: 09:20 and 09:50 select different runs.

**Selection:** for each delivery hour, take the latest eligible run. If none exists, the hour is missing and nothing is filled in. Later runs are never used.

**Comparison:** an hourly forecast is compared with the **mean of the two half-hour actuals** in that hour ("At forecast resolution"); an hour is excluded if either half-hour is missing. A sensitivity option holds the hourly forecast across both half-hours.

**Error = forecast − actual (MW).** Positive = overforecast (less wind than the forecast implied), negative = underforecast.

**Metrics:** MAE, RMSE, bias (mean error), error spread (standard deviation of error), weighted % error (sum of absolute errors ÷ sum of actuals), net error in MWh (MW × step hours). Per-interval MAPE is not used because actuals near zero make it unstable. Counts and coverage are always shown.

## Results for January 2026 (09:20 cutoff, hourly comparison)

From the data snapshot downloaded on 25 Oct 2026. Values may differ slightly if Elexon revises data.

| Metric | Value |
|---|---|
| Matched intervals | 744 of 744 (100%) |
| MAE | 2,038.9 MW |
| RMSE | 2,504.8 MW |
| Bias (forecast − actual) | +1,747.9 MW |
| Weighted error | 18.07% |
| Mean forecast / mean actual (diagnostic) | 13,031 MW / 11,284 MW (ratio 1.155) |

**Key finding.** The forecast ran about **1.7 GW (about 15%) above metered wind**, at nearly every hour of the day and on most days. Diagnostics (`backend/align_check.py`) show this is **not** a timing problem (shifting the comparison window by ±2 hours changes the bias by under 70 MW) and the bias is of similar size (about 1.4–1.9 GW) at every forecast horizon, including 0–6 hours ahead, while MAE grows with horizon (1,676 MW at 0–6 h to 2,317 MW at 48 h+). That pattern points to a **persistent offset** plus ordinary forecast error that grows with lead time.

The cause is **not confirmed**. Possible explanations: the forecast covers wind that the metered transmission-connected series does not; metered output is reduced by grid constraints; or a genuine forecast bias in January. The dashboard reports the offset as observed.

## What the product can and cannot conclude

It shows what forecast was available at the cutoff and how it compared with metered wind. It does **not** calculate a procurement volume, price, imbalance cost or trading position: demand, prices, other generation and positions are outside the permitted scope. Errors are expressed in MW and MWh of wind only. Actuals are transmission-connected metered wind (FUELHH), and the forecast scope may differ.

## Testing

- **14 unit tests** (`python -m pytest -q`): WIND filtering, revised/duplicate actuals, null and duplicate forecasts, London cutoff conversion (GMT and BST), cutoff boundary (inclusive), no later run ever selected, missing forecast stays missing, hourly-to-half-hourly alignment both ways, metric formulas and sign convention, 46/50-interval clock-change days, error spread and horizon buckets, API behaviour with no data.
- **16 end-to-end checks** (`check_api.bat`): endpoints, expected January values, cutoff behaviour, CSV export, bad-input handling, frontend proxy.
- **Verification against source:** `verify_elexon.py` pulls raw responses from the Elexon API and prints schema, cadence, duplicate and vintage diagnostics. Raw JSON can be checked by hand against the dashboard's CSV export.

## Deployment

Deployed on **Vercel** from `Dockerfile.vercel` (React build + FastAPI served from one container). `Dockerfile` and `heroku.yml` support local Docker and Heroku. Vercel functions are stateless and the disk is read-only, so the committed data snapshot is the source of truth and "Refresh from Elexon" only updates memory until the next cold start. The first request after a period of inactivity can take 10–30 seconds.

## Limitations and open questions

- The January interpretation and the 09:20 cutoff are assumptions and need confirmation.
- The cause of the persistent +1.7 GW offset is unconfirmed.
- Whether an hourly forecast value represents the hour starting at `startTime` is not documented in the sources reviewed; the app assumes it does (the alignment diagnostic showed no clear better alternative).
- Elexon may revise data after the snapshot date.
- Pilot scope: January 2026 only, wind only, no persistent database.

## Data attribution

Contains BMRS data © Elexon Limited copyright and database right.
