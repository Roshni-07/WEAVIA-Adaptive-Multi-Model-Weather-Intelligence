"use client";
import dynamic from "next/dynamic";
import { useMemo } from "react";
import { useW, Layer } from "@/lib/store";
import { api, VAR_NAME, VAR_UNIT } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { MODEL_COLOR, VAR_COLOR, n, pct, nice, day, dt, issueLabel } from "@/lib/format";
import { Panel, VarTabs, Weights, Where } from "./ui";
import { SCALE, rampCss } from "./Globe";

const Globe = dynamic(() => import("./Globe"), { ssr: false, loading: () => <div className="gload mono">building globe…</div> });
const LAYERS: { id: Layer; label: string }[] = [
  { id: "rain", label: "Rain" }, { id: "temp", label: "Temperature" }, { id: "wind", label: "Wind speed" },
  { id: "risk", label: "Event risk" }, { id: "weights", label: "Model trust" },
];

export function BandChart({ series, unit, color }: { series: any[]; unit: string; color: string }) {
  const W = 320, H = 130, P = { l: 34, r: 18, t: 8, b: 20 };
  const xs = series.map((s) => s.lead_h), ys = series.flatMap((s) => [s.p10, s.p90, s.blend, s.observed, s.equal]).filter((v) => v !== null && v !== undefined);
  const lo = Math.min(0, ...ys), hi = Math.max(...ys) * 1.08 || 1;
  const X = (l: number) => P.l + ((l - xs[0]) / (xs[xs.length - 1] - xs[0])) * (W - P.l - P.r);
  const Y = (v: number) => H - P.b - ((v - lo) / (hi - lo)) * (H - P.t - P.b);
  const band = series.map((s) => `${X(s.lead_h)},${Y(s.p90)}`).concat([...series].reverse().map((s) => `${X(s.lead_h)},${Y(s.p10)}`)).join(" ");
  const line = (k: string) => series.filter((s) => s[k] !== null).map((s) => `${X(s.lead_h)},${Y(s[k])}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label={`Forecast across lead times with P10 to P90 band, ${unit}`}>
      {[lo, (lo + hi) / 2, hi].map((v, i) => (<g key={i}><line x1={P.l} x2={W - P.r} y1={Y(v)} y2={Y(v)} stroke="#1b2630" /><text x={P.l - 4} y={Y(v) + 3} textAnchor="end" className="ax">{v.toFixed(hi > 20 ? 0 : 1)}</text></g>))}
      {series.map((s) => (<text key={s.lead_h} x={X(s.lead_h)} y={H - 6} textAnchor="middle" className="ax">+{s.lead_h}h</text>))}
      <polygon points={band} fill={color} opacity={0.18} />
      <polyline points={line("equal")} fill="none" stroke="#7d8b94" strokeWidth={1} strokeDasharray="3 3" />
      <polyline points={line("blend")} fill="none" stroke={color} strokeWidth={2} />
      {series.map((s) => s.observed !== null && <circle key={"o" + s.lead_h} cx={X(s.lead_h)} cy={Y(s.observed)} r={3} fill="none" stroke="#f4f1e8" strokeWidth={1.2} />)}
    </svg>
  );
}

function Legend({ layer }: { layer: Layer }) {
  if (layer === "weights") return (
    <div className="legend"><b>Marker = top-weighted model</b>
      <div className="lg">{Object.keys(MODEL_COLOR).map((m) => <span key={m}><i style={{ background: MODEL_COLOR[m] }} />{m.slice(-1).toUpperCase()}</span>)}</div></div>);
  const s = SCALE[layer];
  return (
    <div className="legend"><b>{LAYERS.find((l) => l.id === layer)!.label}</b>
      <div className="ramp" style={{ background: rampCss(layer) }} />
      <div className="mono rl"><span>{s.lo}</span><span>{s.unit}</span><span>{s.hi}{layer === "risk" ? "" : "+"}</span></div>
      <small>{layer === "wind" ? "Speed only. The API carries no wind direction, so no particles are drawn." : "Interpolated between 20 stations, clipped to India."}</small></div>);
}

function Forecast() {
  const { locationId, variable, issue, lead, setView, meta } = useW();
  const ex = useApi(() => api.explain(locationId, variable, issue, lead), [locationId, variable, issue, lead], !!issue);
  const tl = useApi(() => api.timeline(locationId, variable, issue), [locationId, variable, issue], !!issue);
  const d = ex.data, c = VAR_COLOR[variable], u = VAR_UNIT[variable];
  const loc = meta!.locations.find((l) => l.id === locationId)!;
  return (
    <aside className="right" aria-label="Forecast">
      <h1 className="sr">Command Center</h1>
      <div className="rhead"><div><h2>{loc.name}</h2><span className="dim">{nice(loc.region)}{loc.coastal ? " · coastal" : ""}</span></div><VarTabs /></div>
      <Where />
      {ex.error && <p className="err">{ex.error}</p>}
      {d && (<>
        <div className="big mono" style={{ color: c }}>{n(d.forecast.value, variable === "wind" ? 1 : 1)}<small>{u}</small></div>
        <div className="kv">
          <div><span>P10–P90</span><b className="mono">{n(d.forecast.p10)}–{n(d.forecast.p90)}</b></div>
          <div title={d.forecast.confidence_definition}><span>Confidence</span><b className="mono">{pct(d.forecast.confidence)}</b></div>
          <div><span>Event prob.</span><b className="mono">{d.forecast.event_probability === null ? "n/a" : pct(d.forecast.event_probability)}</b></div>
          <div><span>Disagreement</span><b className={"mono lvl " + d.disagreement.level}>{d.disagreement.level}</b></div>
        </div>
        <p className="defn">Confidence = {d.forecast.confidence_definition}. {d.forecast.event_probability === null && "No event model for this variable: too few training events."}</p>
        <div className="reg"><span>Regime</span><b>{nice(d.regime.label)}</b><span className="mono">{pct(d.regime.confidence)}</span></div>
        <p className="narr">{d.narrative}</p>
        {d.case.in_sample_for_meta_model && <p className="warnp">Training-period case: weights were fitted on this date.</p>}
      </>)}
      <Panel title="Across lead times" sub="band = P10–P90 · dashed = equal-weight · ring = observed (verification only)">
        {tl.data ? <BandChart series={tl.data.series} unit={u} color={c} /> : <div className="skel" />}
      </Panel>
      <button className="link" onClick={() => setView("why")}>Why This Forecast</button>
    </aside>
  );
}

function TrustBar() {
  const { locationId, variable, issue, lead, setView, meta } = useW();
  const ex = useApi(() => api.explain(locationId, variable, issue, lead), [locationId, variable, issue, lead], !!issue);
  const ms = ex.data?.models ?? [];
  const w: Record<string, number> = Object.fromEntries(ms.map((m: any) => [m.model_id, m.weight]));
  const order = meta!.models.map((m) => ({ id: m.model_id, color: MODEL_COLOR[m.model_id] }));
  return (
    <div className="trust">
      <div className="thead"><b>Model trust</b><span className="dim">{VAR_NAME[variable]} · +{lead}h · weights sum to 100%</span>
        <button className="link" onClick={() => setView("lab")}>Try Other Weights</button></div>
      {ms.length > 0 && <Weights models={order} w={w} height={16} />}
      <div className="tcols">
        {meta!.models.map((m) => { const d = ms.find((x: any) => x.model_id === m.model_id); return (
          <div key={m.model_id} className="tcol"><i style={{ background: MODEL_COLOR[m.model_id] }} />
            <div><b>{m.name}</b> <span className="mono">{d ? pct(d.weight) : "—"}</span>
              <small>{d ? d.reasons[0] : ""}</small></div></div>); })}
      </div>
    </div>
  );
}

function Timeline() {
  const { meta, issue, setIssue, lead, setLead } = useW();
  const idx = Math.max(0, meta!.issues.indexOf(issue)), L = meta!.leads;
  return (
    <div className="tl">
      <label>Lead time
        <input type="range" min={0} max={L.length - 1} step={1} value={L.indexOf(lead)} onChange={(e) => setLead(L[+e.target.value])} aria-valuetext={`+${lead} hours`} />
        <span className="mono ticks">{L.map((l) => <i key={l} className={l === lead ? "on" : ""}>+{l}h</i>)}</span></label>
      <label>Issue date <span className="mono">{issueLabel(issue)}</span>
        <input type="range" min={0} max={meta!.issues.length - 1} value={idx} onChange={(e) => setIssue(meta!.issues[+e.target.value])} aria-valuetext={issueLabel(issue)} />
        <span className="mono ticks"><i>{issueLabel(meta!.issues[0])}</i><i>{meta!.provenance.data_mode === "real" ? "history + live" : "test slice only"}</i><i>{issueLabel(meta!.issues[meta!.issues.length - 1])}</i></span></label>
    </div>
  );
}

export default function Command() {
  const { map, overview, layer, setLayer, locationId, select } = useW();
  const thr = overview?.alert_thresholds ?? {};
  return (
    <div className="cmd">
      <div className="stage">
        <div className="layers seg" role="tablist" aria-label="Globe layer">
          {LAYERS.map((l) => <button key={l.id} role="tab" aria-selected={layer === l.id} className={layer === l.id ? "on" : ""} style={layer === l.id ? { color: VAR_COLOR[l.id], borderColor: VAR_COLOR[l.id] } : {}} onClick={() => setLayer(l.id)}>{l.label}</button>)}
        </div>
        {map ? <Globe map={map} layer={layer} selected={locationId} onSelect={select} thr={thr} /> : <div className="gload mono">loading…</div>}
        <Legend layer={layer} />
        {overview && (
          <div className="alerts" aria-label="Highest event probabilities">
            <b>Highest event probability</b>
            {overview.alerts.filter((a: any) => a.event_prob >= 0.01).slice(0, 4).map((a: any) => (
              <button key={a.location_id + a.variable} onClick={() => { select(a.location_id); }}>
                <span style={{ color: VAR_COLOR[a.variable] }}>{VAR_NAME[a.variable as "rain"]}</span> {a.name} <span className="mono">{pct(a.event_prob)}</span>
              </button>))}
            {overview.alerts.every((a: any) => a.event_prob < 0.01) && <span className="dim">None above 1% for this issue and lead.</span>}
          </div>)}
      </div>
      <Forecast />
      <div className="below"><TrustBar /><Timeline /></div>
    </div>
  );
}
