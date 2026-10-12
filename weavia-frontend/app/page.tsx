"use client";
import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { useW, View } from "@/lib/store";
import { dt, day, ago, issueLabel } from "@/lib/format";
import Command from "@/components/Command";
import Why from "@/components/Why";
import Regime from "@/components/Regime";
import Models from "@/components/Models";
import Autopsy from "@/components/Autopsy";
import Extremes from "@/components/Extremes";
import Lab from "@/components/Lab";

const NAV: { id: View; label: string; hint: string }[] = [
  { id: "command", label: "Command Center", hint: "Globe, forecast, trust" },
  { id: "why", label: "Why This Forecast", hint: "Reasoning chain" },
  { id: "regime", label: "Regimes", hint: "Atmospheric state" },
  { id: "extremes", label: "Extremes", hint: "Heat wave, heavy rain (IMD)" },
  { id: "models", label: "Models & Skill", hint: "Verified evidence" },
  { id: "autopsy", label: "Autopsy", hint: "Learn from misses" },
  { id: "lab", label: "Lab", hint: "Counterfactual weights" },
];

function Boot({ error, boot }: { error?: string; boot: () => void }) {
  const [sec, setSec] = useState(0);
  useEffect(() => { const t = setInterval(() => setSec((x) => x + 1), 1000); return () => clearInterval(t); }, []);
  useEffect(() => { if (error && sec > 0 && sec % 6 === 0 && sec <= 150) boot(); }, [sec]);   // keep retrying while the server wakes
  const waking = sec >= 4;
  return (
    <main className="boot"><h1>WEAVIA</h1>
      <p className="dim">{waking ? "Waking the demo server. Free hosting sleeps when idle, so the first visit can take a minute or two." : "Loading artifacts…"}</p>
      {waking && <p className="dim mono">{sec}s{error && sec <= 150 ? " · retrying automatically" : ""}</p>}
      {error && sec > 150 && (<><p>API unreachable.</p><pre>{error}</pre>
        <p className="dim">Local setup: <code>cd backend && uvicorn weavia.api.main:app --port 8000</code> (run the pipeline first so <code>data/</code> exists). Override the target with <code>WEAVIA_API</code>.</p></>)}
    </main>
  );
}

export default function Page() {
  const { view, setView, boot, meta, error, loading, issue, map } = useW();
  useEffect(() => { boot(); }, [boot]);

  if (!meta) return <Boot error={error} boot={boot} />;

  return (
    <div className="app">
      <a className="skip" href="#main">Skip to Main Content</a>
      <nav className="nav" aria-label="Primary">
        <div className="brand"><b translate="no">WEAVIA</b><span>adaptive multi-model weather intelligence</span></div>
        {NAV.map((n) => (
          <button key={n.id} className={"navbtn" + (view === n.id ? " on" : "")} onClick={() => setView(n.id)} aria-current={view === n.id ? "page" : undefined}>
            <span>{n.label}</span><small>{n.hint}</small>
          </button>
        ))}
        <div className="navfoot mono">
          <div>{meta.provenance.model_version}</div>
          <div>built {day(meta.provenance.generated_at)}</div>
        </div>
      </nav>
      <div className="main">
        <header className="top">
          <div className={"notice " + (meta.provenance.data_mode === "synthetic" ? "syn" : "")} role="note">
            <b>{meta.provenance.data_mode.toUpperCase()} DATA</b>
            <span>{meta.provenance.data_notice}</span>
          </div>
          {meta.provenance.live && (() => { const L = meta.provenance.live!; const snap = !!L.snapshot; const bad = !snap && (L.stale || L.state !== "ok");
            return (
              <div className={"notice " + (bad ? "syn" : "")} role={bad ? "alert" : "status"}>
                <b>{snap ? "SNAPSHOT" : L.stale ? "STALE" : L.state === "ok" ? "LIVE" : L.state.toUpperCase()}</b>
                <span>
                  {snap ? `real-data snapshot · cycle ${dt(L.issue_time)} · captured ${dt(L.fetched_at)} · frozen, not updating · ` : `cycle ${dt(L.issue_time)} · fetched ${ago(L.age_minutes)} · `}{L.models_ok.length} of {L.models_ok.length + Object.keys(L.models_missing).length} models
                  {Object.keys(L.models_missing).length > 0 && ` · missing: ${Object.keys(L.models_missing).join(", ")}`}
                  {L.state === "failed" && L.reason ? ` · ${L.reason}` : ""}
                  {L.stale ? " · showing the last good forecast, not current data" : ""}
                </span>
              </div>); })()}
          <div className="ctx mono" aria-live="polite">
            {map ? <>issued {issueLabel(map.issue_time)} · valid {dt(map.valid_time)} · +{map.lead_h}h</> : "—"}{loading ? " · updating" : ""}
            {error && <span className="err"> · {error}</span>}
          </div>
        </header>
        <main className="view" id="main" tabIndex={-1}>
          {view === "command" && <Command />}
          {view === "why" && <Why />}
          {view === "regime" && <Regime />}
          {view === "extremes" && <Extremes />}
          {view === "models" && <Models />}
          {view === "autopsy" && <Autopsy />}
          {view === "lab" && <Lab />}
        </main>
      </div>
    </div>
  );
}
