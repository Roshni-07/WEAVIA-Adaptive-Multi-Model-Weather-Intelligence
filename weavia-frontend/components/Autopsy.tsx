"use client";
import { useState } from "react";
import { useW } from "@/lib/store";
import { api, VAR_NAME } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { MODEL_COLOR, n, pct, day, nice } from "@/lib/format";
import { Panel, Err } from "./ui";

export default function Autopsy() {
  const events = useApi(() => api.events(undefined, 80), []);
  const [id, setId] = useState<string>();
  const [lead, setLead] = useState(24);
  const cur = id ?? events.data?.[0]?.event_id;
  const a = useApi(() => api.autopsy(cur!, lead), [cur, lead], !!cur);
  const d = a.data;
  return (
    <div className="page">
      <div className="bar"><h1>Event autopsy</h1>
        <label className="sel">Issued
          <select value={lead} onChange={(e) => setLead(+e.target.value)}>{[24, 48, 72].map((l) => <option key={l} value={l}>{l}h before</option>)}</select></label></div>
      <div className="split">
        <div className="elist" role="listbox" aria-label="Events">{events.data?.map((e: any) => (
          <button key={e.event_id} role="option" aria-selected={e.event_id === cur} className={e.event_id === cur ? "on" : ""} onClick={() => setId(e.event_id)}>
            <b>{e.location}</b><span>{e.event_type} · {VAR_NAME[e.variable as "rain"]}</span><span className="mono">{day(e.valid_time)} · {n(e.observed_value)} {e.unit}</span></button>))}</div>
        <div className="edetail"><Err e={events.error || a.error} />
          {d && (<>
            <Panel title={`${d.event.location} · ${d.event.event_type}`} sub={`valid ${day(d.event.valid_time)} · issued ${day(d.event.issue_time)}`}>
              <div className="kv"><div><span>Observed</span><b className="mono">{n(d.summary.observed)} {d.event.unit}</b></div><div><span>WEAVIA</span><b className="mono">{n(d.summary.weavia)}</b></div>
                <div><span>Error</span><b className="mono">{n(d.summary.error)}</b></div><div><span>Equal weight</span><b className="mono">{n(d.summary.equal_weight)}</b></div>
                <div><span>P10–P90</span><b className="mono">{n(d.summary.p10)}–{n(d.summary.p90)}</b></div><div><span>Event prob.</span><b className="mono">{pct(d.summary.event_probability)}</b></div></div>
              <table className="heat"><thead><tr><th>Model</th><th>Forecast</th><th>Error</th><th>Weight</th><th></th></tr></thead><tbody>
                {d.models.map((m: any) => (<tr key={m.model_id}><th><i className="sw" style={{ background: MODEL_COLOR[m.model_id] }} />{m.name}</th><td className="mono">{n(m.forecast)}</td><td className="mono">{n(m.error)}</td><td className="mono">{pct(m.weight)}</td><td>{m.verdict}</td></tr>))}</tbody></table>
            </Panel>
            <Panel title="Findings">{d.findings.map((f: any) => (<div key={f.step} className="finding"><b>{f.title}</b><p>{f.text}</p></div>))}</Panel>
            <Panel title="What the system learns" sub="trust before vs after this event was verified">
              <table className="heat"><thead><tr><th>Model</th><th>Recent MAE</th><th>Weight next forecast</th></tr></thead><tbody>
                {d.skill_memory.models.map((m: any) => (<tr key={m.model_id}><th>{m.name}</th><td className="mono">{n(m.recent_mae_before, 2)} → {n(m.recent_mae_after, 2)}</td><td className="mono">{pct(m.weight_before)} → {pct(m.weight_after)}</td></tr>))}</tbody></table>
              <p className="narr">{d.lesson}</p>
            </Panel></>)}
        </div>
      </div>
    </div>
  );
}
