"""Run from the backend folder (venv active):  python align_check.py
Reads ../data/snapshot.json. Tests (1) which actual-window best matches an hourly WINDFOR value,
(2) whether the bias is constant across forecast horizons (scope/offset) or grows with horizon (skill)."""
import numpy as np, pandas as pd
from app import core

snap = core.load_snapshot()
fc, act = core.prep_forecasts(snap["forecasts"]), core.prep_actuals(snap["actuals"])
A = act.set_index("startTime")["actual"]
lo, hi = pd.Timestamp("2026-01-02", tz="UTC"), pd.Timestamp("2026-02-01 23:30", tz="UTC")


def stats(e):
    e = e.dropna()
    return dict(n=len(e), bias=round(e.mean()), mae=round(e.abs().mean()), rmse=round(float(np.sqrt((e ** 2).mean()))))


def window_mean(starts, off_min):
    a = A.reindex(starts + pd.Timedelta(minutes=off_min)).values
    b = A.reindex(starts + pd.Timedelta(minutes=off_min + 30)).values
    return (a + b) / 2


# 1) alignment: decision-cutoff selection (09:20), actual window = two half-hours starting at T+offset
sel = pd.concat([core.select_vintage(fc, d.date(), "09:20") for d in pd.date_range("2026-01-02", "2026-02-01")])
print("== 1. Alignment test (cutoff 09:20 forecasts; window = mean of 2 half-hours starting T+offset) ==")
for off in range(-120, 121, 30):
    e = pd.Series(sel["forecast"].values - window_mean(sel["startTime"], off))
    print(f"offset {off:+4d} min:", stats(e))

# 2) horizon dependence using ALL vintages (diagnostic only, not a decision-time metric)
x = fc[(fc.startTime >= lo) & (fc.startTime <= hi)].copy()
x["h"] = (x.startTime - x.publishTime).dt.total_seconds() / 3600
x = x[x.h >= 0]
x["err"] = x["forecast"].values - window_mean(x["startTime"], 0)
x["bucket"] = pd.cut(x.h, [0, 6, 12, 24, 36, 48, 80], right=False)
print("\n== 2. Error by horizon (hours between publish and delivery start), all vintages ==")
print(x.groupby("bucket", observed=True)["err"].agg(n="count", bias="mean", mae=lambda s: s.abs().mean()).round(0))

# 3) ratio
m = pd.DataFrame({"f": sel["forecast"].values, "a": window_mean(sel["startTime"], 0)}).dropna()
print("\n== 3. Sum(forecast)/Sum(actual) at cutoff:", round(m.f.sum() / m.a.sum(), 3), "(1.0 = no scale difference)")
print("Mean actual MW:", round(m.a.mean()), " Mean forecast MW:", round(m.f.mean()))
