"use client";
import { useW } from "@/lib/store";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { n, pct, nice } from "@/lib/format";
import { Panel, Where, LeadSel, Err } from "./ui";

export default function Regime() {
  const { locationId, issue, lead, map, select } = useW();
  const { data: d, error } = useApi(() => api.regime(locationId, issue, lead), [locationId, issue, lead], !!issue);
  const ver = d?.classifier_verification;
  const order = d ? Object.entries(d.probabilities).sort((a: any, b: any) => b[1] - a[1]) : [];
  return (
    <div className="page">
      <div className="bar"><h1>Weather regimes</h1><Where /><LeadSel /></div>
      <Err e={error} />
      <div className="two">
        <Panel title={d ? `${nice(d.label)} · ${pct(d.confidence)}` : "Regime"} sub="classifier probabilities for the selected case">
          {d && <>
            {order.map(([r, p]: any) => (<div key={r} className="prow"><span>{nice(r)}</span><div className="pbar"><i style={{ width: `${p * 100}%` }} /></div><span className="mono">{pct(p, 1)}</span></div>))}
            <p className="defn">Regime derived afterwards from observations: <b>{nice(d.observed_regime)}</b>. {d.observed_regime === d.label ? "Matches the prediction." : "Differs from the prediction."}</p>
          </>}
        </Panel>
        <Panel title="Across India" sub="predicted regime per station">
          <div className="rgrid">{map?.points.map((p) => (
            <button key={p.location_id} className={p.location_id === locationId ? "on" : ""} onClick={() => select(p.location_id)}>
              <b>{p.name}</b><span>{nice(p.regime)}</span><span className="mono">{pct(p.regime_confidence)}</span></button>))}</div>
        </Panel>
        {ver && (
          <Panel title="Classifier verification" sub="held-out test slice">
            <p className="defn mono">accuracy {pct(ver.accuracy, 1)} vs majority-class baseline {pct(ver.majority_baseline, 1)} ({nice(ver.majority_class)}). Recall by regime:</p>
            {Object.entries(ver.recall).map(([r, v]: any) => (<div key={r} className="prow"><span>{nice(r)}</span><div className="pbar"><i style={{ width: `${v * 100}%` }} /></div><span className="mono">{pct(v)}</span></div>))}
            <p className="defn">Rare regimes (heavy rain, high wind) are recognised far less often than normal weather; read regime-specific trust with that in mind.</p>
          </Panel>)}
      </div>
    </div>
  );
}
