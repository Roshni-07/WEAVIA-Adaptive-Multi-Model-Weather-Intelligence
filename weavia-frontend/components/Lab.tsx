"use client";
import { useEffect, useState } from "react";
import { useW } from "@/lib/store";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { MODEL_COLOR, n, pct } from "@/lib/format";
import { Panel, VarTabs, Where, LeadSel, Err } from "./ui";

export default function Lab() {
  const { meta, locationId, variable, issue, lead } = useW();
  const base = useApi(() => api.explain(locationId, variable, issue, lead), [locationId, variable, issue, lead], !!issue);
  const [w, setW] = useState<Record<string, number>>({});
  const [scope, setScope] = useState("global");
  const [same, setSame] = useState(false);
  useEffect(() => { if (base.data) setW(Object.fromEntries(base.data.models.map((m: any) => [m.model_id, Math.round(m.weight * 100)]))); }, [base.data]);
  const [out, setOut] = useState<any>(); const [err, setErr] = useState<string>();
  useEffect(() => {
    if (!Object.keys(w).length || !issue) return;
    const t = setTimeout(() => api.lab({ location_id: locationId, variable, issue, lead, weights: w, scope, same_regime: same }).then((r) => { setOut(r); setErr(undefined); }).catch((e) => setErr(e.message)), 250);
    return () => clearTimeout(t);
  }, [w, scope, same, locationId, variable, issue, lead]);
  const sum = Object.values(w).reduce((a, b) => a + b, 0) || 1;
  const h = out?.historical, f = out?.forecast, u = base.data?.case.unit;
  return (
    <div className="page">
      <div className="bar"><h1>Lab</h1><Where /><LeadSel /><VarTabs /></div>
      <div className="two">
        <Panel title="Counterfactual weights" sub="weights are renormalised to sum to 100%">
          {meta!.models.map((m) => (
            <label key={m.model_id} className="wsl"><span><i className="sw" style={{ background: MODEL_COLOR[m.model_id] }} />{m.name}</span>
              <input type="range" min={0} max={100} value={w[m.model_id] ?? 0} onChange={(e) => setW({ ...w, [m.model_id]: +e.target.value })} />
              <span className="mono">{pct((w[m.model_id] ?? 0) / sum)}</span></label>))}
          <div className="row"><button className="btn" onClick={() => setW(Object.fromEntries(meta!.models.map((m) => [m.model_id, 25])))}>Equal</button>
            <button className="btn" onClick={() => base.data && setW(Object.fromEntries(base.data.models.map((m: any) => [m.model_id, Math.round(m.weight * 100)])))}>Reset to WEAVIA</button></div>
          <label className="sel">Back-test scope<select value={scope} onChange={(e) => setScope(e.target.value)}><option value="global">All stations</option><option value="region">Same region</option><option value="location">This station</option></select></label>
          <label className="chk"><input type="checkbox" checked={same} onChange={(e) => setSame(e.target.checked)} /> Only cases in the same predicted regime</label>
        </Panel>
        <Panel title="Result">
          <Err e={err} />
          {out && f && (<>
            <div className="kv"><div><span>WEAVIA</span><b className="mono">{n(f.weavia, 2)} {u}</b></div><div><span>Your weights</span><b className="mono">{n(f.counterfactual, 2)}</b></div>
              <div><span>Change</span><b className="mono">{f.change > 0 ? "+" : ""}{n(f.change, 2)}</b></div><div><span>Observed</span><b className="mono">{n(f.observed, 2)}</b></div></div>
            <p className="defn">This single case is descriptive, not evidence. The back-test below is the fair comparison.</p>
            {h ? (<div className="verdict"><b>{h.verdict}</b>
              <p className="mono">n={h.n} test cases · MAE: yours {n(h.mae_counterfactual, 3)} · WEAVIA {n(h.mae_weavia, 3)} · equal {n(h.mae_equal, 3)} ({n(h.change_vs_weavia_pct)}% vs WEAVIA)</p></div>) : <p className="defn">Too few test cases in this scope for a back-test (need 20+).</p>}
            <h4>Leave one model out</h4>
            {out.leave_one_out.map((l: any) => (<div key={l.model_id} className="prow"><span>{l.name}</span><span className="mono">{n(l.without_model, 2)}</span><span className="mono">{l.change > 0 ? "+" : ""}{n(l.change, 2)}</span></div>))}
            <p className="narr">{out.driver}</p></>)}
        </Panel>
      </div>
    </div>
  );
}
