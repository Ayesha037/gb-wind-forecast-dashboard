# GB Wind Forecast: Day-Ahead Check

Shows the wind forecast (Elexon WINDFOR) that was available at a day-ahead decision cutoff and compares it with metered wind (Elexon FUELHH, WIND). National GB data only.

**Live app:** _add URL after deploy_  |  **Demo video:** _add unlisted YouTube link_

## AI assistance disclosure
Designed and written with substantial help from Anthropic's Claude (research, architecture, code, tests, documentation). The author ran, reviewed and verified the result against Elexon data.

## Run on Windows
1. Double-click `setup.bat` (venv, tests, downloads Jan 2026 data to `data/snapshot.json`, npm install).
2. Double-click `start_all.bat`. App: http://localhost:5173 (API: http://localhost:8000/api/meta).
Manual: `cd backend`, `.venv\Scripts\activate`, `python -m pytest`, `uvicorn app.main:app --port 8000`; second terminal `cd frontend`, `npm run dev`.

## Self-check
`check.bat` (unit tests + frontend build), then `start_all.bat`, then `check_api.bat` (PASS/FAIL for every API endpoint and the frontend proxy).

## Deploy (free): Vercel
`npm install -g vercel`, `vercel login`, `vercel`, then `vercel --prod` from this folder. Vercel builds `Dockerfile.vercel`. (Hobby-plan support for container deploys is unverified.)

## Docker / Heroku (after `data/snapshot.json` exists)
```
docker build -t wind .
docker run -p 8000:8000 wind
heroku create && heroku stack:set container && heroku container:push web && heroku container:release web
```

## Method (assumptions unconfirmed unless stated)
- Scope: decision date in Jan 2026 => delivery 2 Jan to 1 Feb. *Assumption.*
- Cutoff: 09:20 Europe/London on D-1 (09:50 selectable). Eligible = `publishTime <= cutoff`. *Assumption.*
- Verified on real data (5-7 Jan sample + full-month snapshot): WINDFOR is hourly, ~8 runs/day at :30 past, history retrievable with `publishDateTimeFrom/To`; no filter returns only the latest run; the settlement-date filter is ignored by WINDFOR. FUELHH is half-hourly with `publishTime`, no duplicates or gaps seen.
- Selection: per delivery hour, latest eligible run; later runs never used; missing stays missing.
- Comparison: hourly forecast vs mean of both half-hour actuals ("native"), or hourly forecast held across half-hours ("hold").
- Error = forecast - actual (MW); positive = overforecast. MAE, RMSE, bias, error SD, weighted % error (sum|e|/sum actual), net MWh = MW x step hours.

## Key finding and caveat
Over Jan 2026 the forecast ran ~1.7 GW (~15%) above metered wind at every horizon (`backend/align_check.py`). Timing offsets do not explain it. Cause unconfirmed (possible scope/definition difference, constraint/curtailment effects, or real forecast bias).

## Limitations
Wind only: no demand, price, other generation or positions, so no procurement volume, price or imbalance cost.

Contains BMRS data © Elexon Limited copyright and database right.
