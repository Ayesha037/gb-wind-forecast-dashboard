from datetime import date
import pandas as pd
import pytest
from app import core
from app.core import prep_actuals, prep_forecasts, select_vintage, compare_day, metrics, cutoff_utc, detect_resolution_minutes


def fc_rows(pubs, starts, val):
    return [{"publishTime": p, "startTime": s, "generation": val(p, s)} for p in pubs for s in starts]


def test_wind_filter_and_dedupe_revision():
    rows = [{"startTime": "2026-01-05T00:00:00Z", "publishTime": "2026-01-05T00:35:00Z", "fuelType": "WIND", "generation": 100},
            {"startTime": "2026-01-05T00:00:00Z", "publishTime": "2026-01-05T01:00:00Z", "fuelType": "WIND", "generation": 110},
            {"startTime": "2026-01-05T00:00:00Z", "publishTime": "2026-01-05T00:35:00Z", "fuelType": "CCGT", "generation": 999}]
    a = prep_actuals(rows)
    assert len(a) == 1 and a.actual.iloc[0] == 110  # latest published wins, CCGT dropped


def test_forecast_null_and_duplicate_dropped():
    rows = [{"publishTime": "2026-01-04T04:30:00Z", "startTime": "2026-01-05T00:00:00Z", "generation": None},
            {"publishTime": "2026-01-04T04:30:00Z", "startTime": "2026-01-05T01:00:00Z", "generation": 5},
            {"publishTime": "2026-01-04T04:30:00Z", "startTime": "2026-01-05T01:00:00Z", "generation": 6}]
    f = prep_forecasts(rows)
    assert len(f) == 1 and f.forecast.iloc[0] == 6


def test_cutoff_is_london_time_and_gmt_in_january():
    assert cutoff_utc(date(2026, 1, 5)).isoformat() == "2026-01-04T09:20:00+00:00"


def test_cutoff_bst_edge():  # July: London 09:20 = 08:20 UTC
    assert cutoff_utc(date(2026, 7, 5)).isoformat() == "2026-07-04T08:20:00+00:00"


def test_vintage_never_uses_later_run_and_boundary_inclusive():
    starts = ["2026-01-05T12:00:00Z"]
    pubs = ["2026-01-04T04:30:00Z", "2026-01-04T09:20:00Z", "2026-01-04T09:21:00Z"]
    fc = prep_forecasts(fc_rows(pubs, starts, lambda p, s: pubs.index(p)))
    sel = select_vintage(fc, date(2026, 1, 5), "09:20")
    assert sel.forecast.iloc[0] == 1  # 09:20 inclusive, 09:21 excluded


def test_no_eligible_forecast_is_missing_not_filled():
    fc = prep_forecasts(fc_rows(["2026-01-04T10:00:00Z"], ["2026-01-05T12:00:00Z"], lambda p, s: 1))
    assert select_vintage(fc, date(2026, 1, 5), "09:20").empty


def test_cutoff_choice_changes_run_only_if_run_between():
    pubs = ["2026-01-04T09:30:00Z"]
    fc = prep_forecasts(fc_rows(pubs, ["2026-01-05T12:00:00Z"], lambda p, s: 1))
    assert select_vintage(fc, date(2026, 1, 5), "09:20").empty
    assert len(select_vintage(fc, date(2026, 1, 5), "09:50")) == 1


def test_hourly_native_alignment_and_metrics():
    # hourly forecast, half-hourly actuals; two hours
    fc = prep_forecasts(fc_rows(["2026-01-04T04:30:00Z"], ["2026-01-05T00:00:00Z", "2026-01-05T01:00:00Z"], lambda p, s: 100))
    act = prep_actuals([{"startTime": t, "generation": g, "fuelType": "WIND"} for t, g in
                        [("2026-01-05T00:00:00Z", 90), ("2026-01-05T00:30:00Z", 110), ("2026-01-05T01:00:00Z", 80)]])
    m = compare_day(fc, act, date(2026, 1, 5), "09:20", "native", res=60)
    ok = m.dropna(subset=["error"])
    assert len(ok) == 1 and ok.error.iloc[0] == 0   # hour0: mean 100 -> err 0; hour1 missing half-hour -> excluded
    assert metrics(m)["missing_actual"] == 23 and metrics(m)["n_matched"] == 1


def test_hold_alignment_half_hourly():
    fc = prep_forecasts(fc_rows(["2026-01-04T04:30:00Z"], ["2026-01-05T00:00:00Z"], lambda p, s: 100))
    act = prep_actuals([{"startTime": t, "generation": g, "fuelType": "WIND"} for t, g in
                        [("2026-01-05T00:00:00Z", 90), ("2026-01-05T00:30:00Z", 120)]])
    m = compare_day(fc, act, date(2026, 1, 5), "09:20", "hold", res=60)
    ok = m.dropna(subset=["error"])
    assert list(ok.error) == [10, -20]
    mt = metrics(ok.assign(delivery_date="x"))
    assert mt["mae"] == 15 and mt["bias"] == -5 and round(mt["rmse"], 1) == round(((100 + 400) / 2) ** 0.5, 1)
    assert mt["net_error_mwh"] == -5   # (10-20) MW * 0.5h


def test_metrics_sign_convention_over_is_positive():
    m = pd.DataFrame({"forecast": [120.0], "actual": [100.0], "error": [20.0], "step_hours": [0.5], "startTime": [pd.Timestamp("2026-01-05", tz="UTC")]})
    assert metrics(m)["bias"] == 20.0


def test_resolution_detection():
    f = prep_forecasts(fc_rows(["2026-01-04T04:30:00Z"], ["2026-01-05T00:00:00Z", "2026-01-05T01:00:00Z", "2026-01-05T02:00:00Z"], lambda p, s: 1))
    assert detect_resolution_minutes(f) == 60


def test_dst_day_has_46_or_50_intervals():
    s, e = core.day_bounds_utc(date(2026, 3, 29))   # spring forward: 23h
    assert (e - s).total_seconds() / 1800 == 46
    s, e = core.day_bounds_utc(date(2026, 10, 25))  # fall back: 25h
    assert (e - s).total_seconds() / 1800 == 50


def test_api_errors_when_no_data():
    from fastapi.testclient import TestClient
    from app.main import app, S
    S["fc"] = S["fc"].iloc[0:0]; S["error"] = "boom"
    r = TestClient(app).get("/api/day?decision_date=2026-01-04")
    assert r.status_code == 503 and "boom" in r.text


def test_error_sd_and_horizon_buckets():
    m = pd.DataFrame({"forecast": [110.0, 130.0], "actual": [100.0, 100.0], "error": [10.0, 30.0], "step_hours": [1.0, 1.0],
                      "horizon_h": [20.0, 32.0], "startTime": pd.to_datetime(["2026-01-05", "2026-01-05"], utc=True), "delivery_date": ["a", "a"]})
    assert metrics(m)["error_sd"] == round(float(pd.Series([10.0, 30.0]).std()), 1)
    bh = core.by_horizon(m)
    assert [b["bucket"] for b in bh] == ["18-24h", "30-36h"] and bh[1]["bias"] == 30.0
