"""Run with backend running on :8000 (frontend on :5173 optional). Prints PASS/FAIL per check.
Expected numbers are for the Jan 2026 snapshot downloaded on 25 Oct 2026; if Elexon revised data they may differ slightly."""
import sys, requests
B, F = "http://localhost:8000", "http://localhost:5173"
res = []
def chk(name, ok, detail=""):
    res.append(ok); print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))
def near(a, b, tol=1.0): return a is not None and abs(a - b) <= tol
def get(path):
    try: return requests.get(B + path, timeout=60)
    except Exception as e: print("FAIL  cannot reach backend:", e); sys.exit(1)

m = get("/api/meta").json()
chk("meta: source snapshot/live, no error", m["source"] in ("snapshot", "live") and m["error"] is None, f'{m["source"]} / {m["error"]}')
chk("meta: forecast resolution 60 min", m["forecast"].get("resolution_min") == 60, m["forecast"].get("resolution_min"))
chk("meta: 276 publish times / 20148 rows", (m["forecast"].get("distinct_publishTimes"), m["forecast"].get("rows")) == (276, 20148), (m["forecast"].get("distinct_publishTimes"), m["forecast"].get("rows")))
chk("meta: actuals 1536 rows, 0 missing", (m["actuals"]["rows"], m["actuals"]["missing_generation"]) == (1536, 0))

a = get("/api/metrics?from=2026-01-02&to=2026-02-01&cutoff=09:20&align=native").json()["metrics"]
chk("range metrics: 744/744 matched", (a["n_matched"], a["n_expected"]) == (744, 744), (a["n_matched"], a["n_expected"]))
chk("range metrics: MAE ~2038.9", near(a.get("mae"), 2038.9), a.get("mae"))
chk("range metrics: bias ~1747.9", near(a.get("bias"), 1747.9), a.get("bias"))

d = get("/api/day?decision_date=2026-01-15&cutoff=09:20&align=native").json()
chk("day 15 Jan: run used 07:30 UTC", d["selected_publishTimes"] == ["2026-01-15T07:30:00+00:00"], d["selected_publishTimes"])
chk("day 15 Jan: MAE ~782.8, bias ~352", near(d["metrics"].get("mae"), 782.8) and near(d["metrics"].get("bias"), 352.0), (d["metrics"].get("mae"), d["metrics"].get("bias")))
d2 = get("/api/day?decision_date=2026-01-15&cutoff=09:50&align=native").json()
chk("cutoff 09:50 selects a different (later) run", d2["selected_publishTimes"] == ["2026-01-15T09:30:00+00:00"], d2["selected_publishTimes"])

e = get("/api/evolution?start_time=2026-01-16T00:00:00Z&cutoff=09:20").json()
chk("evolution: vintages returned, some after cutoff", len(e["vintages"]) > 5 and any(not v["eligible"] for v in e["vintages"]), len(e["vintages"]))
c = get("/api/export.csv?from=2026-01-02&to=2026-01-03&cutoff=09:20&align=native")
chk("csv export: header + rows", c.status_code == 200 and c.text.startswith("startTime,publishTime,forecast,actual,error") and c.text.count("\n") > 20, c.text.split("\n")[0][:60])
o = get("/api/day?decision_date=2025-06-01")
chk("out-of-range date does not crash (no 5xx)", o.status_code < 500, o.status_code)
chk("API still alive after bad request", get("/api/meta").status_code == 200)
try:
    r = requests.get(F, timeout=10); chk("frontend reachable on :5173", r.status_code == 200 and "root" in r.text, r.status_code)
    p = requests.get(F + "/api/meta", timeout=30); chk("frontend proxy -> backend works", p.status_code == 200 and "forecast" in p.json(), p.status_code)
except Exception as ex:
    print("SKIP  frontend not running on :5173 (start it with npm run dev):", type(ex).__name__)
print(f"\n{sum(res)}/{len(res)} checks passed")
sys.exit(0 if all(res) else 1)
