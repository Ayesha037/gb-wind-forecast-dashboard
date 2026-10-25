import io
from datetime import date, timedelta
from pathlib import Path
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from . import core

app = FastAPI(title="UK Wind Forecast Dashboard")
S = {"fc": pd.DataFrame(), "act": pd.DataFrame(), "source": "none", "fetched_at": None, "error": None}


def _load(snap, source):
    S["fc"], S["act"] = core.prep_forecasts(snap["forecasts"]), core.prep_actuals(snap["actuals"])
    S["source"], S["fetched_at"], S["error"] = source, snap.get("fetched_at"), None


@app.on_event("startup")
def startup():
    snap = core.load_snapshot()
    if snap:
        _load(snap, "snapshot")
        return
    try:
        snap = core.fetch_live(); core.save_snapshot(snap); _load(snap, "live")
    except Exception as e:  # keep app up and show the problem in the UI
        S["error"] = str(e)


def _need_data():
    if S["fc"].empty or S["act"].empty:
        raise HTTPException(503, S["error"] or "No data loaded. POST /api/refresh or provide data/snapshot.json")


def _range(scope, d0, d1):
    return (d0, d1)


@app.post("/api/refresh")
def refresh():
    try:
        snap = core.fetch_live(); core.save_snapshot(snap); _load(snap, "live")
    except Exception as e:
        S["error"] = str(e); raise HTTPException(502, str(e))
    return meta()


@app.get("/api/meta")
def meta():
    fc, act = S["fc"], S["act"]
    return {"source": S["source"], "fetched_at": S["fetched_at"], "error": S["error"],
            "forecast": core.cadence_info(fc),
            "actuals": {"rows": int(len(act)), "distinct_startTimes": int(act["startTime"].nunique()) if len(act) else 0,
                        "missing_generation": int(act["actual"].isna().sum()) if len(act) else 0},
            "defaults": {"cutoff": core.DEFAULT_CUTOFF, "from": "2026-01-02", "to": "2026-02-01"},
            "assumptions": ["Decision date in Jan 2026 => delivery 2 Jan-1 Feb (unconfirmed interpretation).",
                            f"Cutoff {core.DEFAULT_CUTOFF} Europe/London on D-1 (assumption; 09:50 selectable).",
                            "error = forecast - actual; positive = overforecast.",
                            "Actuals are transmission-connected metered wind (FUELHH); forecast scope may differ.",
                            "Units: MW (average); MWh = MW x step hours."],
            "attribution": "Contains BMRS data © Elexon Limited copyright and database right."}


@app.get("/api/day")
def day(decision_date: date, cutoff: str = core.DEFAULT_CUTOFF, align: str = "native"):
    _need_data()
    d = decision_date + timedelta(days=1)
    m = core.compare_day(S["fc"], S["act"], d, cutoff, align)
    sel = m["publishTime"].dropna()
    rows = [{"time": r.startTime.isoformat(), "forecast": None if pd.isna(r.forecast) else r.forecast,
             "actual": None if pd.isna(r.actual) else r.actual, "error": None if pd.isna(r.error) else r.error,
             "publishTime": None if pd.isna(r.publishTime) else r.publishTime.isoformat()} for r in m.itertuples()]
    return {"decision_date": decision_date.isoformat(), "delivery_date": d.isoformat(),
            "cutoff_utc": core.cutoff_utc(d, cutoff).isoformat(),
            "selected_publishTimes": sorted({t.isoformat() for t in sel}),
            "metrics": core.metrics(m), "rows": rows}


@app.get("/api/metrics")
def metrics(date_from: date = Query(alias="from"), date_to: date = Query(alias="to"),
            cutoff: str = core.DEFAULT_CUTOFF, align: str = "native"):
    _need_data()
    m = core.compare_range(S["fc"], S["act"], date_from, date_to, cutoff, align)
    return {"metrics": core.metrics(m), "by_hour": core.by_hour(m), "by_day": core.by_day(m), "by_horizon": core.by_horizon(m)}


@app.get("/api/evolution")
def evolution(start_time: str, cutoff: str = core.DEFAULT_CUTOFF):
    _need_data()
    t = pd.Timestamp(start_time).tz_convert("UTC") if pd.Timestamp(start_time).tzinfo else pd.Timestamp(start_time, tz="UTC")
    v = S["fc"][S["fc"].startTime == t].sort_values("publishTime")
    a = S["act"][S["act"].startTime == t]
    d = t.tz_convert(core.LON).date()
    cut = core.cutoff_utc(d, cutoff)
    return {"start_time": t.isoformat(), "cutoff_utc": cut.isoformat(),
            "actual": None if a.empty or pd.isna(a.actual.iloc[0]) else float(a.actual.iloc[0]),
            "vintages": [{"publishTime": r.publishTime.isoformat(), "forecast": r.forecast, "eligible": bool(r.publishTime <= cut)} for r in v.itertuples()]}


@app.get("/api/export.csv")
def export(date_from: date = Query(alias="from"), date_to: date = Query(alias="to"),
           cutoff: str = core.DEFAULT_CUTOFF, align: str = "native"):
    _need_data()
    m = core.compare_range(S["fc"], S["act"], date_from, date_to, cutoff, align)
    buf = io.StringIO(); m.drop(columns=["step_hours"]).to_csv(buf, index=False)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=wind_forecast_vs_actual.csv"})


STATIC = Path(__file__).parent.parent / "static"
if STATIC.exists():
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
