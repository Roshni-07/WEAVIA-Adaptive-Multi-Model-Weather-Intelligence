"use client";
import { useW } from "@/lib/store";
import { api, VAR_NAME, VAR_UNIT, VARS } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { MODEL_COLOR, n, pct, nice } from "@/lib/format";
import { Panel, VarTabs, LeadSel } from "./ui";

export default function Models() {
  const { variable, lead, meta } = useW();
  const atlas = useApi(() => api.skillAtlas(variable, lead), [variable, lead]);
  const ver = useApi(() => api.verification(), []);
  const cell = (reg: string, m: string) => atlas.data?.cells.find((c: any) => c.regime === reg && c.model_id === m);
  const maxMae = atlas.data ? Math.max(...atlas.data.cells.map((c: any) => c.mae)) : 1;
  const V = ver.data?.verification;
  return (
    <div className="page">
      <div className="bar"><h1>Models &amp; skill</h1><LeadSel /><VarTabs /></div>
      <div className="two">
        <Panel title="Skill atlas" sub={`verified MAE (${VAR_UNIT[variable]}) by regime · training-period error memory · lower is better · outline = best per row`}>
          {atlas.data && (<div className="scroll"><table className="heat"><thead><tr><th>Regime</th>{atlas.data.models.map((m: any) => <th key={m.model_id}>{m.name}<small>{m.label}</small></th>)}</tr></thead>
            <tbody>{atlas.data.regimes.map((r: string) => {
              const row = atlas.data.models.map((m: any) => cell(r, m.model_id)); const best = Math.min(...row.filter(Boolean).map((c: any) => c.mae));
              return (<tr key={r}><th>{nice(r)}</th>{row.map((c: any, i: number) => c ? (
                <td key={i} className={c.mae === best ? "best" : ""} style={{ background: `rgba(53,195,216,${0.05 + 0.5 * (c.mae / maxMae)})` }} title={`n=${c.n}, bias ${n(c.bias, 2)}`}><span className="mono">{n(c.mae, 2)}</span><small>n={c.n}</small></td>) : <td key={i} className="na">—</td>)}</tr>);
            })}</tbody></table></div>)}
          {atlas.data && (<><h4>By region (all regimes)</h4><div className="scroll"><table className="heat"><thead><tr><th>Region</th>{atlas.data.models.map((m: any) => <th key={m.model_id}>{m.name}</th>)}</tr></thead><tbody>
            {Object.entries(atlas.data.by_region).map(([rg, v]: any) => { const best = Math.min(...Object.values(v).filter((x: any) => x !== null) as number[]); return (
              <tr key={rg}><th>{nice(rg)}</th>{atlas.data.models.map((m: any) => <td key={m.model_id} className={v[m.model_id] === best ? "best" : ""}><span className="mono">{n(v[m.model_id], 2)}</span></td>)}</tr>); })}</tbody></table></div></>)}
        </Panel>
        <Panel title="Does WEAVIA beat the baselines?" sub="held-out test slice · paired bootstrap 95% CI on MAE change">
          {meta!.provenance.data_mode === "synthetic" && <p className="warnp">Synthetic data. These numbers validate the machinery; they are not evidence of real-world skill.</p>}
          {V && (<div className="scroll"><table className="heat"><thead><tr><th>Variable</th><th>WEAVIA MAE</th><th>Equal</th><th>vs equal</th><th>Best single</th><th>vs best (train-picked)</th></tr></thead><tbody>
            {V.headline.map((h: any) => { const b = h.vs_best_single_train; return (
              <tr key={h.variable}><th>{VAR_NAME[h.variable as "rain"]}</th><td className="mono">{n(h.weavia_mae, 3)}</td><td className="mono">{n(h.equal_mae, 3)}</td>
                <td className="mono">{n(h.vs_equal.improvement_pct)}% [{n(h.vs_equal.ci95_pct[0])}, {n(h.vs_equal.ci95_pct[1])}]<small>{h.vs_equal.significant ? "CI excludes 0" : "CI includes 0: no claim"}</small></td>
                <td className="mono">{h.best_single_model?.slice(-1).toUpperCase()} {n(h.best_single_mae, 3)}</td>
                <td className="mono">{b ? <>{n(b.improvement_pct)}% [{n(b.ci95_pct?.[0])}, {n(b.ci95_pct?.[1])}]<small>{b.significant ? "CI excludes 0" : "CI includes 0: no claim"}</small></> : "—"}</td></tr>); })}</tbody></table></div>)}
          {V && (<><h4>Interval coverage (P10–P90, nominal 80%)</h4><div className="scroll"><table className="heat"><thead><tr><th>Var</th>{[6, 12, 24, 48, 72].map((l) => <th key={l}>+{l}h</th>)}</tr></thead><tbody>
            {VARS.map((v) => (<tr key={v}><th>{VAR_NAME[v]}</th>{[6, 12, 24, 48, 72].map((l) => { const c = V.coverage.find((x: any) => x.variable === v && x.lead_h === l); return <td key={l} className="mono">{c ? pct(c.inside_p10_p90) : "—"}</td>; })}</tr>))}</tbody></table></div></>)}
          {V && (<><h4>Event detection (test slice)</h4>{V.events.map((e: any) => (<p key={e.variable} className="defn mono">{VAR_NAME[e.variable as "rain"]} ≥ {e.threshold}: {e.n_obs_events} observed events{e.n_obs_events < 30 ? " (too few for a skill claim)" : ""}{e.n_obs_events >= 30 && e.methods?.weavia_event_model ? ` · WEAVIA event-model F1 ${n(e.methods.weavia_event_model.f1, 2)}` : ""}</p>))}</>)}
        </Panel>
      </div>
    </div>
  );
}
