import json, os, time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import requests

LON = ZoneInfo("Europe/London")
BASE = os.getenv("ELEXON_BASE", "https://data.elexon.co.uk/bmrs/api/v1")
SNAPSHOT = os.getenv(
    "SNAPSHOT_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data", "snapshot.json")
)
DEFAULT_CUTOFF = "09:20"  # ASSUMPTION: D-1 London time (EPEX GB day-ahead closure). Configurable.

def _get(path, params, timeout=60, retries=3):
    last = None
    for i in range(retries):
        try:
            r = requests.get(f"{BASE}{path}", params=params, timeout=timeout, headers={"Accept": "application/json"})
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"HTTP {r.status_code}"; time.sleep(2 ** (i + 1)); continue
            r.raise_for_status()
            data = r.json()
            return data.get("data", data) if isinstance(data, dict) else data
        except (requests.RequestException, ValueError) as e:
            last = repr(e); time.sleep(2 ** (i + 1))
    raise RuntimeError(f"Elexon request failed: {path} {params} -> {last}")


def fetch_live(start="2026-01-01", end="2026-02-01"):
    """Fetch WIND actuals and ALL WINDFOR vintages published in the window (publish-time filtered, 3-day chunks)."""
    actuals = _get("/datasets/FUELHH/stream", {"settlementDateFrom": start, "settlementDateTo": end, "fuelType": "WIND"})
    pub_start = datetime.fromisoformat(start) - timedelta(days=3)
    pub_end = datetime.fromisoformat(end) + timedelta(hours=11)
    fc, t = [], pub_start
    while t < pub_end:
        t2 = min(t + timedelta(days=3), pub_end)
        fc += _get("/datasets/WINDFOR/stream", {"publishDateTimeFrom": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                                 "publishDateTimeTo": t2.strftime("%Y-%m-%dT%H:%M:%SZ")})
        t = t2
    return {"fetched_at": datetime.now(timezone.utc).isoformat(), "actuals": actuals, "forecasts": fc}


def load_snapshot():
    if os.path.exists(SNAPSHOT):
        with open(SNAPSHOT) as f:
            return json.load(f)
    return None


def save_snapshot(snap):
    try:  # read-only filesystems (e.g. serverless) just keep the data in memory
        os.makedirs(os.path.dirname(SNAPSHOT), exist_ok=True)
        with open(SNAPSHOT, "w") as f:
            json.dump(snap, f)
    except OSError:
        pass


# ---------- normalisation ----------
def prep_actuals(rows):
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["startTime", "actual"])
    if "fuelType" in df:
        df = df[df["fuelType"].astype(str).str.upper() == "WIND"]
    df["startTime"] = pd.to_datetime(df["startTime"], utc=True)
    df["generation"] = pd.to_numeric(df["generation"], errors="coerce")
    if "publishTime" in df:  # keep latest published value per interval (handles revisions)
        df["publishTime"] = pd.to_datetime(df["publishTime"], utc=True)
        df = df.sort_values("publishTime")
    df = df.drop_duplicates("startTime", keep="last")
    return df.rename(columns={"generation": "actual"})[["startTime", "actual"]].sort_values("startTime").reset_index(drop=True)


def prep_forecasts(rows):
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["startTime", "publishTime", "forecast"])
    df["startTime"] = pd.to_datetime(df["startTime"], utc=True)
    df["publishTime"] = pd.to_datetime(df["publishTime"], utc=True)
    df["generation"] = pd.to_numeric(df["generation"], errors="coerce")
    df = df.dropna(subset=["generation"]).drop_duplicates(["startTime", "publishTime"], keep="last")
    return df.rename(columns={"generation": "forecast"})[["startTime", "publishTime", "forecast"]].reset_index(drop=True)


def detect_resolution_minutes(fc):
    st = np.sort(fc["startTime"].unique())
    if len(st) < 2:
        return None
    d = np.diff(st).astype("timedelta64[m]").astype(int)
    return int(pd.Series(d).mode().iloc[0])

def cutoff_utc(delivery_date, hhmm=DEFAULT_CUTOFF):
    """Cutoff = D-1 at hh:mm Europe/London, returned in UTC."""
    h, m = map(int, hhmm.split(":"))
    d = delivery_date - timedelta(days=1)
    return pd.Timestamp(datetime(d.year, d.month, d.day, h, m, tzinfo=LON)).tz_convert("UTC")


def day_bounds_utc(delivery_date):
    s = pd.Timestamp(datetime(delivery_date.year, delivery_date.month, delivery_date.day, tzinfo=LON)).tz_convert("UTC")
    e = pd.Timestamp(datetime.combine(delivery_date + timedelta(days=1), datetime.min.time(), tzinfo=LON)).tz_convert("UTC")
    return s, e


def select_vintage(fc, delivery_date, hhmm=DEFAULT_CUTOFF):
    """For each delivery interval of D: latest forecast with publishTime <= cutoff. Never uses later runs."""
    s, e = day_bounds_utc(delivery_date)
    c = cutoff_utc(delivery_date, hhmm)
    x = fc[(fc.startTime >= s) & (fc.startTime < e) & (fc.publishTime <= c)]
    return x.sort_values("publishTime").groupby("startTime", as_index=False).last()


def compare_day(fc, act, delivery_date, hhmm=DEFAULT_CUTOFF, align="native", res=None):
    """Return matched frame. align: 'native' (compare at forecast resolution) or 'hold' (hourly forecast held over half-hours)."""
    s, e = day_bounds_utc(delivery_date)
    sel = select_vintage(fc, delivery_date, hhmm)
    a = act[(act.startTime >= s) & (act.startTime < e)].copy()
    res = res or detect_resolution_minutes(fc) or 30
    if res == 60 and align == "native":
        a["hour"] = a["startTime"].dt.floor("h")
        g = a.groupby("hour")["actual"].agg(["mean", "count"]).reset_index()
        g = g[g["count"] == 2]  # require both half-hours, else missing
        a = g.rename(columns={"hour": "startTime", "mean": "actual"})[["startTime", "actual"]]
        step = 1.0
        grid = pd.date_range(s, e, freq="60min", inclusive="left")
    elif res == 60 and align == "hold":
        step = 0.5
        sel = sel.copy(); sel["hour"] = sel["startTime"]
        grid = pd.date_range(s, e, freq="30min", inclusive="left")
        h = pd.DataFrame({"startTime": grid}); h["hour"] = h["startTime"].dt.floor("h")
        sel = h.merge(sel[["hour", "publishTime", "forecast"]], on="hour", how="left").drop(columns="hour")
    else:
        step = res / 60
        grid = pd.date_range(s, e, freq=f"{res}min", inclusive="left")
    m = pd.DataFrame({"startTime": grid}).merge(sel[["startTime", "publishTime", "forecast"]], on="startTime", how="left") \
        .merge(a[["startTime", "actual"]], on="startTime", how="left")
    m["error"] = m["forecast"] - m["actual"]  # + = overforecast, - = underforecast
    m["delivery_date"] = delivery_date.isoformat()
    m["step_hours"] = step
    m["horizon_h"] = (m["startTime"] - m["publishTime"]).dt.total_seconds() / 3600
    return m


def compare_range(fc, act, d0, d1, hhmm=DEFAULT_CUTOFF, align="native"):
    res = detect_resolution_minutes(fc) or 30
    days = [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]
    return pd.concat([compare_day(fc, act, d, hhmm, align, res) for d in days], ignore_index=True)


# ---------- metrics ----------
def metrics(m):
    ok = m.dropna(subset=["error"])
    n, total = len(ok), len(m)
    out = {"n_matched": n, "n_expected": total, "missing_forecast": int(m["forecast"].isna().sum()),
           "missing_actual": int(m["actual"].isna().sum()), "coverage_pct": round(100 * n / total, 1) if total else None}
    if n:
        e = ok["error"]
        out.update(mae=round(float(e.abs().mean()), 1), rmse=round(float(np.sqrt((e ** 2).mean())), 1),
                   bias=round(float(e.mean()), 1), error_sd=round(float(e.std()), 1),
                   wape_pct=round(100 * float(e.abs().sum() / ok["actual"].sum()), 2) if ok["actual"].sum() > 0 else None,
                   net_error_mwh=round(float((e * ok["step_hours"]).sum()), 0))
    return out


def by_hour(m):
    ok = m.dropna(subset=["error"]).copy()
    ok["hour"] = ok["startTime"].dt.tz_convert(LON).dt.hour
    g = ok.groupby("hour")["error"].agg(bias="mean", mae=lambda s: s.abs().mean(), n="count").round(1).reset_index()
    return g.to_dict("records")


def by_horizon(m):
    ok = m.dropna(subset=["error", "horizon_h"]).copy()
    if ok.empty:
        return []
    ok["b"] = pd.cut(ok["horizon_h"], [0, 18, 24, 30, 36, 48], right=False)
    g = ok.groupby("b", observed=True)["error"].agg(bias="mean", mae=lambda s: s.abs().mean(), n="count").round(1).reset_index()
    g["bucket"] = g["b"].apply(lambda i: f"{int(i.left)}-{int(i.right)}h")
    return g[["bucket", "bias", "mae", "n"]].to_dict("records")


def by_day(m):
    ok = m.dropna(subset=["error"])
    g = ok.groupby("delivery_date")["error"].agg(bias="mean", mae=lambda s: s.abs().mean(), n="count").round(1).reset_index()
    return g.to_dict("records")


def cadence_info(fc):
    if fc.empty:
        return {}
    p = fc["publishTime"].drop_duplicates().sort_values()
    gaps = p.diff().dropna().dt.total_seconds() / 3600
    return {"distinct_publishTimes": int(len(p)), "distinct_startTimes": int(fc["startTime"].nunique()),
            "resolution_min": detect_resolution_minutes(fc), "rows": int(len(fc)),
            "publish_gap_hours_median": round(float(gaps.median()), 2) if len(gaps) else None,
            "publish_hours_utc": sorted(p.dt.hour.unique().tolist()),
            "first_publish": p.iloc[0].isoformat(), "last_publish": p.iloc[-1].isoformat()}
