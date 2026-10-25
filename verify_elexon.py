#!/usr/bin/env python3
"""Elexon FUELHH / WINDFOR data-verification script (stdlib only, Python 3.9+).

Usage:
    python verify_elexon.py                      # defaults: 5-7 Jan 2026
    python verify_elexon.py --start 2026-01-05 --end 2026-01-07 --out fixtures
On Windows you may need:  pip install tzdata

It saves every raw response under --out and writes diagnostics.json.
It reports only what the API actually returned; failures are recorded, not hidden.
"""
import argparse, json, os, sys, time, collections, statistics
import urllib.request, urllib.parse, urllib.error
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LON = ZoneInfo("Europe/London")
DEFAULT_BASE = "https://data.elexon.co.uk/bmrs/api/v1"


def get(base, path, params, out_dir, label, timeout=60, retries=3):
    """GET with timeout, retry on 429/5xx/network errors. Returns (rows|None, record)."""
    url = f"{base}{path}?{urllib.parse.urlencode(params)}"
    rec = {"label": label, "url": url, "attempts": []}
    for attempt in range(1, retries + 1):
        t0 = time.time()
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json",
                                                       "User-Agent": "verify-elexon/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
                rec["attempts"].append({"status": r.status, "secs": round(time.time() - t0, 2),
                                        "bytes": len(body), "content_type": r.headers.get("Content-Type")})
            path_out = os.path.join(out_dir, f"{label}.json")
            with open(path_out, "wb") as f:
                f.write(body)
            rec["saved_to"] = path_out
            try:
                data = json.loads(body)
            except json.JSONDecodeError as e:
                rec["error"] = f"JSON decode error: {e}"
                return None, rec
            rec["top_level_type"] = type(data).__name__
            if isinstance(data, dict):
                rec["top_level_keys"] = list(data.keys())
                data = data.get("data", data)
            return data, rec
        except urllib.error.HTTPError as e:
            snippet = e.read()[:300].decode("utf-8", "replace")
            rec["attempts"].append({"status": e.code, "secs": round(time.time() - t0, 2), "body_snippet": snippet})
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2 ** attempt)
                continue
            rec["error"] = f"HTTP {e.code}"
            return None, rec
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            rec["attempts"].append({"error": repr(e), "secs": round(time.time() - t0, 2)})
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            rec["error"] = f"network error: {e!r}"
            return None, rec
    return None, rec


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if isinstance(s, str) else None


def describe_rows(rows):
    d = {"n_rows": len(rows)}
    if not rows:
        return d
    d["fields"] = sorted({k for r in rows for k in r})
    d["sample_first"], d["sample_last"] = rows[0], rows[-1]
    d["generation_nulls"] = sum(1 for r in rows if r.get("generation") is None)
    d["timestamp_formats_seen"] = sorted({
        ("Z-suffix" if str(r.get(k, "")).endswith("Z") else "other:" + str(r.get(k)))
        for r in rows[:200] for k in ("startTime", "publishTime") if k in r})
    return d


def analyse_fuelhh(rows, start, end):
    d = describe_rows(rows)
    if not rows:
        return d
    d["fuelTypes"] = dict(collections.Counter(r.get("fuelType") for r in rows))
    d["settlementPeriod_range"] = [min(r["settlementPeriod"] for r in rows if "settlementPeriod" in r),
                                   max(r["settlementPeriod"] for r in rows if "settlementPeriod" in r)] \
        if any("settlementPeriod" in r for r in rows) else None
    wind = [r for r in rows if r.get("fuelType") == "WIND"] or rows
    keyc = collections.Counter(r["startTime"] for r in wind)
    d["distinct_startTime"] = len(keyc)
    d["duplicated_startTime_count"] = sum(1 for c in keyc.values() if c > 1)
    by = collections.defaultdict(set)
    for r in wind:
        by[r["startTime"]].add(r.get("generation"))
    d["startTimes_with_conflicting_generation"] = sum(1 for v in by.values() if len(v) > 1)
    d["distinct_publishTime"] = len({r.get("publishTime") for r in wind if "publishTime" in r})
    # expected half-hours in window (UTC, from London midnight to next London midnight)
    s = datetime.fromisoformat(start).replace(tzinfo=LON)
    e = datetime.fromisoformat(end).replace(tzinfo=LON) + timedelta(days=1)
    expected, t = set(), s.astimezone(timezone.utc)
    while t < e.astimezone(timezone.utc):
        expected.add(t.strftime("%Y-%m-%dT%H:%M:%SZ")); t += timedelta(minutes=30)
    got = {ts(k).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") for k in keyc}
    d["expected_half_hours"] = len(expected)
    d["missing_half_hours"] = sorted(expected - got)[:50]
    d["n_missing_half_hours"] = len(expected - got)
    d["unexpected_half_hours"] = len(got - expected)
    if rows and "generation" in wind[0]:
        vals = [r["generation"] for r in wind if r.get("generation") is not None]
        if vals:
            d["generation_min_max_mean"] = [min(vals), max(vals), round(statistics.mean(vals), 1)]
    return d


def analyse_windfor(rows):
    d = describe_rows(rows)
    if not rows:
        return d
    pubs = sorted({r["publishTime"] for r in rows})
    starts = sorted({r["startTime"] for r in rows})
    d["distinct_publishTime"] = len(pubs)
    d["distinct_startTime"] = len(starts)
    d["publishTime_first_last"] = [pubs[0], pubs[-1]]
    pt = [ts(p) for p in pubs]
    gaps = [(b - a).total_seconds() / 3600 for a, b in zip(pt, pt[1:])]
    if gaps:
        d["publish_gap_hours_min_median_max"] = [round(min(gaps), 2), round(statistics.median(gaps), 2), round(max(gaps), 2)]
    d["publish_minute_of_hour_hist"] = dict(collections.Counter(p.minute for p in pt))
    d["publish_hour_UTC_hist"] = dict(sorted(collections.Counter(p.hour for p in pt).items()))
    st = [ts(s) for s in starts]
    sg = sorted({int((b - a).total_seconds() / 60) for a, b in zip(st, st[1:])})
    d["startTime_spacing_minutes_seen"] = sg[:10]
    d["startTime_minute_hist"] = dict(collections.Counter(s.minute for s in st))
    per_pub = collections.Counter(r["publishTime"] for r in rows)
    d["rows_per_publishTime_min_median_max"] = [min(per_pub.values()), statistics.median(per_pub.values()), max(per_pub.values())]
    key = collections.Counter((r["startTime"], r["publishTime"]) for r in rows)
    d["duplicate_(startTime,publishTime)_keys"] = sum(1 for c in key.values() if c > 1)
    vint = collections.Counter(r["startTime"] for r in rows)
    d["vintages_per_startTime_min_median_max"] = [min(vint.values()), statistics.median(vint.values()), max(vint.values())]
    hz = [(ts(r["startTime"]) - ts(r["publishTime"])).total_seconds() / 3600 for r in rows]
    d["horizon_hours_min_median_max"] = [round(min(hz), 2), round(statistics.median(hz), 2), round(max(hz), 2)]
    d["rows_with_startTime_before_publishTime"] = sum(1 for h in hz if h < 0)
    return d


def cutoff_demo(rows, delivery_dates):
    """For each delivery date D, report which publishTime is selected at D-1 09:20 and 09:50 London."""
    out = {}
    pubs = sorted({ts(r["publishTime"]) for r in rows})
    for D in delivery_dates:
        day = datetime.fromisoformat(D).date()
        res = {}
        for hhmm in ("09:20", "09:50"):
            h, m = map(int, hhmm.split(":"))
            cut = datetime(day.year, day.month, day.day, h, m, tzinfo=LON) - timedelta(days=1)
            el = [p for p in pubs if p <= cut.astimezone(timezone.utc)]
            res[hhmm] = el[-1].strftime("%Y-%m-%dT%H:%M:%SZ") if el else None
        res["cutoff_choice_changes_selected_run"] = res["09:20"] != res["09:50"]
        out[D] = res
    return out


def match_test(fuel_rows, wind_rows):
    act = {ts(r["startTime"]) for r in fuel_rows if r.get("fuelType", "WIND") == "WIND"}
    fc = {ts(r["startTime"]) for r in wind_rows}
    if not fc:
        return {}
    return {"forecast_startTimes": len(fc), "of_which_present_in_actuals": len(fc & act),
            "forecast_startTimes_on_half_hour_not_hour": sum(1 for t in fc if t.minute == 30),
            "actual_half_hours_without_forecast_startTime": len(act - fc)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--start", default="2026-01-05", help="first delivery/settlement date (YYYY-MM-DD)")
    ap.add_argument("--end", default="2026-01-07", help="last delivery/settlement date")
    ap.add_argument("--out", default="fixtures")
    ap.add_argument("--timeout", type=int, default=60)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    report = {"base": a.base, "run_at_utc": datetime.now(timezone.utc).isoformat(), "requests": [], "results": {}}

    s_dt = datetime.fromisoformat(a.start); e_dt = datetime.fromisoformat(a.end)
    pub_from = (s_dt - timedelta(days=2)).strftime("%Y-%m-%dT00:00:00Z")   # covers runs before first cutoff
    pub_to = (e_dt + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")

    def run(path, params, label):
        rows, rec = get(a.base, path, params, a.out, label, a.timeout)
        report["requests"].append(rec)
        print(f"[{label}] -> {'OK ' + str(len(rows)) + ' rows' if rows is not None else 'FAILED ' + str(rec.get('error'))}")
        return rows

    # 1 FUELHH actuals, WIND only, by settlement date
    fuel = run("/datasets/FUELHH/stream", {"settlementDateFrom": a.start, "settlementDateTo": a.end, "fuelType": "WIND"}, "fuelhh_wind_by_settlement")
    # 1b FUELHH by publish window (revision check; also shows whether publishTime exists)
    fuel_pub = run("/datasets/FUELHH/stream", {"publishDateTimeFrom": pub_from, "publishDateTimeTo": pub_to, "fuelType": "WIND"}, "fuelhh_wind_by_publish")
    # 2 WINDFOR vintages by publish window
    wind = run("/datasets/WINDFOR/stream", {"publishDateTimeFrom": pub_from, "publishDateTimeTo": pub_to}, "windfor_by_publish_window")
    # 2b WINDFOR with no filters (expected: latest only; shows 'today', i.e. NOT January)
    wind_nofilter = run("/datasets/WINDFOR/stream", {}, "windfor_no_filter")
    # 2c datetime-format variant (no seconds)
    run("/datasets/WINDFOR/stream", {"publishDateTimeFrom": f"{a.start}T00:00Z", "publishDateTimeTo": f"{a.start}T12:00Z"}, "windfor_format_variant_no_seconds")
    # 2d settlement-date filter on WINDFOR (check whether that parameter is honoured)
    run("/datasets/WINDFOR/stream", {"settlementDateFrom": a.start, "settlementDateTo": a.start}, "windfor_by_settlement_date")

    if fuel:
        report["results"]["fuelhh_by_settlement"] = analyse_fuelhh(fuel, a.start, a.end)
    if fuel_pub:
        report["results"]["fuelhh_by_publish"] = analyse_fuelhh(fuel_pub, a.start, a.end)
    if wind:
        report["results"]["windfor_by_publish_window"] = analyse_windfor(wind)
        days = [(s_dt + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((e_dt - s_dt).days + 1)]
        report["results"]["cutoff_demo"] = cutoff_demo(wind, days)
    if wind_nofilter:
        d = analyse_windfor(wind_nofilter)
        report["results"]["windfor_no_filter"] = {k: d.get(k) for k in
            ("n_rows", "distinct_publishTime", "publishTime_first_last", "distinct_startTime")}
    if fuel and wind:
        report["results"]["timestamp_match_test"] = match_test(fuel, wind)

    with open(os.path.join(a.out, "diagnostics.json"), "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(json.dumps(report["results"], indent=2, default=str))
    failed = [r["label"] for r in report["requests"] if "error" in r]
    print("\nFAILED REQUESTS:", failed or "none")
    print(f"Saved raw responses + diagnostics.json in ./{a.out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
