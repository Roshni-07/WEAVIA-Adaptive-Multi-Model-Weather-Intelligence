"use client";
import { useW } from "@/lib/store";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { MODEL_COLOR, n, pct } from "@/lib/format";
import { Panel, VarTabs, Where, LeadSel, Err } from "./ui";

export default function Why() {
  const { locationId, variable, issue, lead } = useW();
  const { data: d, error } = useApi(() => api.explain(locationId, variable, issue, lead), [locationId, variable, issue, lead], !!issue);
  return (
    <div className="page">
      <div className="bar"><h1>Why this forecast</h1><Where /><LeadSel /><VarTabs /></div>
      <Err e={error} />
      {d && (<div className="two">
        <Panel title="Reasoning chain" sub="every step is read from the pipeline output">
          <ol className="chain">{d.chain.map((s: any) => (
            <li key={s.key}><div className="ct">{s.title}</div><div className="cv mono">{s.value}</div><div className="cd">{s.detail}</div></li>))}</ol>
          <p className="narr">{d.narrative}</p>
        </Panel>
        <Panel title="Per-model evidence" sub={`meta-model temperature τ = ${d.meta_model_tau}`}>
          <div className="mcards">{d.models.map((m: any) => (
            <div key={m.model_id} className="mcard" style={{ borderLeftColor: MODEL_COLOR[m.model_id] }}>
              <div className="mh"><b>{m.name}</b><span className="dim">{m.label}</span><span className="mono w">{pct(m.weight)}</span></div>
              <div className="mono mm">forecast {n(m.forecast, 2)} · equal {pct(m.equal_weight)} · inverse-error {pct(m.inverse_error_weight)} · predicted |err| {n(m.predicted_error, 2)}</div>
              <ul>{m.reasons.map((r: string, i: number) => <li key={i}>{r}</li>)}</ul>
              <div className="drv">{m.drivers.map((x: any) => <span key={x.feature} className={x.direction === "raises trust" ? "up" : "dn"}>{x.label}: {x.direction}</span>)}</div>
            </div>))}</div>
        </Panel>
      </div>)}
    </div>
  );
}
