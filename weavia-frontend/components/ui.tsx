"use client";
import { ReactNode } from "react";
import { useW } from "@/lib/store";
import { VARS, VAR_NAME } from "@/lib/api";
import { VAR_COLOR } from "@/lib/format";

export function Panel({ title, sub, children, className = "" }: { title?: string; sub?: string; children: ReactNode; className?: string }) {
  return (<div className={"panel " + className}>{title && <h2>{title}{sub && <small>{sub}</small>}</h2>}{children}</div>);
}
export function VarTabs() {
  const { variable, setVariable } = useW();
  return (
    <div className="seg" role="tablist" aria-label="Variable">
      {VARS.map((v) => (
        <button key={v} role="tab" aria-selected={variable === v} className={variable === v ? "on" : ""} style={variable === v ? { color: VAR_COLOR[v], borderColor: VAR_COLOR[v] } : {}} onClick={() => setVariable(v)}>{VAR_NAME[v]}</button>
      ))}
    </div>
  );
}
export function Where() {
  const { meta, locationId, select } = useW();
  return (
    <label className="sel">Location
      <select value={locationId} onChange={(e) => select(e.target.value)}>
        {meta!.locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
      </select>
    </label>
  );
}
export function LeadSel() {
  const { meta, lead, setLead } = useW();
  return (
    <label className="sel">Lead
      <select value={lead} onChange={(e) => setLead(+e.target.value)}>{meta!.leads.map((l) => <option key={l} value={l}>+{l}h</option>)}</select>
    </label>
  );
}
export function Err({ e }: { e?: string }) { return e ? <p className="err">{e}</p> : null; }
export function Weights({ models, w, height = 14 }: { models: { id: string; color: string }[]; w: Record<string, number>; height?: number }) {
  return (
    <div className="wbar" style={{ height }} role="img" aria-label={models.map((m) => `${m.id} ${(w[m.id] * 100).toFixed(0)}%`).join(", ")}>
      {models.map((m) => <i key={m.id} style={{ width: `${w[m.id] * 100}%`, background: m.color }} />)}
    </div>
  );
}
