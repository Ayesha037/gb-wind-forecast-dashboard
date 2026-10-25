import React, { useEffect, useMemo, useState } from "react";
import { ResponsiveContainer, LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, Legend, CartesianGrid, ReferenceLine } from "recharts";

const j = async (u) => { const r = await fetch(u); if (!r.ok) throw new Error((await r.text()).slice(0, 300)); return r.json(); };
const hhmm = (iso) => new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/London" });
const ts = (iso) => new Date(iso).toLocaleString("en-GB", { timeZone: "Europe/London", dateStyle: "medium", timeStyle: "short" });
const fmt = (v, u = "") => (v === null || v === undefined ? "n/a" : `${Number(v).toLocaleString("en-GB")}${u}`);

export default function App() {
  const [meta, setMeta] = useState(null), [err, setErr] = useState(null);
  const [decision, setDecision] = useState("2026-01-15"), [cutoff, setCutoff] = useState("09:20"), [align, setAlign] = useState("native");
  const [from, setFrom] = useState("2026-01-02"), [to, setTo] = useState("2026-02-01");
  const [day, setDay] = useState(null), [agg, setAgg] = useState(null), [evo, setEvo] = useState(null), [evoT, setEvoT] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { j("/api/meta").then(setMeta).catch((e) => setErr(e.message)); }, []);
  useEffect(() => {
    setErr(null);
    j(`/api/day?decision_date=${decision}&cutoff=${cutoff}&align=${align}`).then((d) => { setDay(d); setEvoT(d.rows.find((r) => r.forecast != null)?.time || ""); }).catch((e) => setErr(e.message));
  }, [decision, cutoff, align]);
  useEffect(() => { j(`/api/metrics?from=${from}&to=${to}&cutoff=${cutoff}&align=${align}`).then(setAgg).catch((e) => setErr(e.message)); }, [from, to, cutoff, align]);
  useEffect(() => { if (evoT) j(`/api/evolution?start_time=${encodeURIComponent(evoT)}&cutoff=${cutoff}`).then(setEvo).catch(() => setEvo(null)); }, [evoT, cutoff]);

  const refresh = async () => { setBusy(true); try { await fetch("/api/refresh", { method: "POST" }).then((r) => { if (!r.ok) throw new Error("Refresh failed: Elexon unreachable. Using existing data."); }); setMeta(await j("/api/meta")); } catch (e) { setErr(e.message); } setBusy(false); };
  const rows = useMemo(() => (day?.rows || []).map((r) => ({ ...r, t: hhmm(r.time) })), [day]);
  const m = day?.metrics, a = agg?.metrics, fc = meta?.forecast;
  const dq = meta && (meta.error || m?.coverage_pct < 90);

  return (<>
    <header>
      <h1>What did the wind forecast say when we had to buy?</h1>
      <p className="sub">Great Britain wind, day-ahead. For each delivery day, we use only the latest forecast published before your cutoff on the day before, then compare it with metered wind output.</p>
    </header>
    <main>
      <section className="controls" aria-label="Controls">
        <label>Decision date<input type="date" value={decision} min="2026-01-01" max="2026-01-31" onChange={(e) => setDecision(e.target.value)} /></label>
        <label>Cutoff (UK time, day before)<select value={cutoff} onChange={(e) => setCutoff(e.target.value)}><option>09:20</option><option>09:50</option></select></label>
        <label>Comparison<select value={align} onChange={(e) => setAlign(e.target.value)}><option value="native">At forecast resolution</option><option value="hold">Half-hourly (forecast held)</option></select></label>
        <label>Metrics from<input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
        <label>to<input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
        <a className="btn" href={`/api/export.csv?from=${from}&to=${to}&cutoff=${cutoff}&align=${align}`}>Download CSV</a>
        <button onClick={refresh} disabled={busy}>{busy ? "Refreshing…" : "Refresh from Elexon"}</button>
      </section>

      {err && <div className="warn err" role="alert">{err}</div>}

      {day && <section className="panel banner">
        Decision on <b>{day.decision_date}</b> for delivery on <b>{day.delivery_date}</b>. Cutoff {ts(day.cutoff_utc)}.{" "}
        {day.selected_publishTimes.length ? <>Forecast runs used: <b>{day.selected_publishTimes.map(ts).join("; ")}</b>.</> : <b>No forecast was published before the cutoff.</b>}
      </section>}

      {m && <section className="stats panel" aria-label="Selected day metrics">
        {[["MAE", m.mae, " MW"], ["RMSE", m.rmse, " MW"], ["Bias (forecast − actual)", m.bias, " MW"], ["Error spread (SD)", m.error_sd, " MW"], ["Weighted error", m.wape_pct, "%"], ["Net error", m.net_error_mwh, " MWh"], ["Coverage", m.coverage_pct, `% (${m.n_matched}/${m.n_expected})`]]
          .map(([k, v, u]) => <div className="stat" key={k}><b>{fmt(v, u)}</b><span>{k}</span></div>)}
      </section>}

      <section className="panel"><h2>Forecast vs actual: delivery day</h2>
        <ResponsiveContainer width="100%" height={320}><LineChart data={rows}>
          <CartesianGrid stroke="var(--line)" /><XAxis dataKey="t" interval={5} /><YAxis unit=" MW" width={80} /><Tooltip /><Legend />
          <Line dataKey="forecast" name="Forecast (at cutoff)" stroke="var(--fc)" dot={false} strokeWidth={2} connectNulls={false} />
          <Line dataKey="actual" name="Actual (FUELHH)" stroke="var(--ac)" dot={false} strokeWidth={2} strokeDasharray="5 3" connectNulls={false} />
        </LineChart></ResponsiveContainer>
        <p className="note">Positive error means the forecast was higher than actual wind (overforecast): less wind than planned. Gaps mean missing data; nothing is filled in.</p>
      </section>

      <div className="two">
        <section className="panel"><h2>Average error by delivery hour (selected range)</h2>
          <ResponsiveContainer width="100%" height={260}><BarChart data={agg?.by_hour || []}>
            <CartesianGrid stroke="var(--line)" /><XAxis dataKey="hour" /><YAxis width={70} /><Tooltip /><ReferenceLine y={0} stroke="var(--ink)" />
            <Legend /><Bar dataKey="bias" name="Bias (MW)" fill="var(--over)" /><Bar dataKey="mae" name="MAE (MW)" fill="var(--under)" /></BarChart></ResponsiveContainer></section>
        <section className="panel"><h2>Error by day (selected range)</h2>
          <ResponsiveContainer width="100%" height={260}><BarChart data={agg?.by_day || []}>
            <CartesianGrid stroke="var(--line)" /><XAxis dataKey="delivery_date" tickFormatter={(d) => d.slice(5)} /><YAxis width={70} /><Tooltip /><ReferenceLine y={0} stroke="var(--ink)" />
            <Legend /><Bar dataKey="bias" name="Bias (MW)" fill="var(--over)" /><Bar dataKey="mae" name="MAE (MW)" fill="var(--under)" /></BarChart></ResponsiveContainer></section>
      </div>

      <section className="panel"><h2>Error by hours ahead of delivery (decision-time forecasts)</h2>
        <ResponsiveContainer width="100%" height={240}><BarChart data={agg?.by_horizon || []}>
          <CartesianGrid stroke="var(--line)" /><XAxis dataKey="bucket" /><YAxis width={70} /><Tooltip /><Legend /><ReferenceLine y={0} stroke="var(--ink)" />
          <Bar dataKey="bias" name="Bias (MW)" fill="var(--over)" /><Bar dataKey="mae" name="MAE (MW)" fill="var(--under)" /></BarChart></ResponsiveContainer>
        <p className="note">Hours ahead = delivery time minus publication time. For forecasts chosen at the cutoff this is tied to the delivery hour (00:00 is about 15 hours ahead, 23:00 about 38), so this chart mixes time of day with horizon and does not show how skill changes with lead time. A bias of similar size in every bucket points to a persistent offset (scope or definition difference between forecast and metered wind), which should be confirmed before relying on the forecast level.</p></section>

      {a && <section className="panel"><h2>Whole range</h2>
        <p>MAE <b>{fmt(a.mae, " MW")}</b>, RMSE <b>{fmt(a.rmse, " MW")}</b>, bias <b>{fmt(a.bias, " MW")}</b>, weighted error <b>{fmt(a.wape_pct, "%")}</b>. Matched {a.n_matched} of {a.n_expected} intervals ({fmt(a.coverage_pct, "%")}); missing forecast {a.missing_forecast}, missing actual {a.missing_actual}.</p></section>}

      <section className="panel"><h2>How one interval's forecast changed over time</h2>
        <label>Delivery interval<select value={evoT} onChange={(e) => setEvoT(e.target.value)}>{rows.filter((r) => r.forecast != null).map((r) => <option key={r.time} value={r.time}>{r.t}</option>)}</select></label>
        {evo && <ResponsiveContainer width="100%" height={260}><LineChart data={evo.vintages.map((v) => ({ ...v, p: ts(v.publishTime) }))}>
          <CartesianGrid stroke="var(--line)" /><XAxis dataKey="p" hide /><YAxis unit=" MW" width={80} domain={["auto", "auto"]} /><Tooltip />
          <Line dataKey="forecast" stroke="var(--fc)" name="Forecast by publication" dot={(p) => (p.cx == null ? null : <circle key={p.index} cx={p.cx} cy={p.cy} r={4} fill={p.payload.eligible ? "var(--fc)" : "var(--mut)"} />)} />
          {evo.actual != null && <ReferenceLine y={evo.actual} stroke="var(--ink)" strokeDasharray="4 3" label={{ value: "actual", position: "insideTopRight", fill: "var(--ink)" }} />}</LineChart></ResponsiveContainer>}
        <p className="note">Grey points were published after the cutoff ({evo ? ts(evo.cutoff_utc) : ""}) and were not available to the decision. Hover for publication times.</p></section>

      <section className="panel"><h2>Data quality</h2>
        {meta && <table><tbody>
          <tr><th>Source</th><td>{meta.source}{meta.fetched_at && `, fetched ${ts(meta.fetched_at)}`}</td></tr>
          <tr><th>Forecast rows / publish times / delivery times</th><td>{fc?.rows ?? "n/a"} / {fc?.distinct_publishTimes ?? "n/a"} / {fc?.distinct_startTimes ?? "n/a"}</td></tr>
          <tr><th>Detected forecast resolution</th><td>{fc?.resolution_min ? `${fc.resolution_min} minutes` : "n/a"}; median gap between runs {fmt(fc?.publish_gap_hours_median, " h")}</td></tr>
          <tr><th>Actuals rows / missing values</th><td>{meta.actuals.rows} / {meta.actuals.missing_generation}</td></tr></tbody></table>}
        <p className="note">Assumptions: {meta?.assumptions.join(" ")} This shows wind only: it does not calculate a procurement volume, price, or imbalance cost.</p>
        <p className="note">{meta?.attribution}</p></section>
    </main></>);
}
