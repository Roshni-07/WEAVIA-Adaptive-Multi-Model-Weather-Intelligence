"use client";
import { useEffect } from "react";
import dynamic from "next/dynamic";
import { useW, View } from "@/lib/store";
import { dt, day } from "@/lib/format";
import Command from "@/components/Command";
import Why from "@/components/Why";
import Regime from "@/components/Regime";
import Models from "@/components/Models";
import Autopsy from "@/components/Autopsy";
import Lab from "@/components/Lab";

const NAV: { id: View; label: string; hint: string }[] = [
  { id: "command", label: "Command Center", hint: "Globe, forecast, trust" },
  { id: "why", label: "Why This Forecast", hint: "Reasoning chain" },
  { id: "regime", label: "Regimes", hint: "Atmospheric state" },
  { id: "models", label: "Models & Skill", hint: "Verified evidence" },
  { id: "autopsy", label: "Autopsy", hint: "Learn from misses" },
  { id: "lab", label: "Lab", hint: "Counterfactual weights" },
];

export default function Page() {
  const { view, setView, boot, meta, error, loading, issue, map } = useW();
  useEffect(() => { boot(); }, [boot]);

  if (error && !meta) return (
    <main className="boot"><h1>WEAVIA</h1><p>API unreachable.</p><pre>{error}</pre>
      <p className="dim">Start it: <code>cd backend && uvicorn weavia.api.main:app --port 8000</code> (run the pipeline first so <code>data/</code> exists). Override the target with <code>WEAVIA_API</code>.</p></main>
  );
  if (!meta) return <main className="boot"><h1>WEAVIA</h1><p className="dim">Loading artifacts…</p></main>;

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
          <div className="ctx mono" aria-live="polite">
            {map ? <>issued {day(map.issue_time)} · valid {dt(map.valid_time)} · +{map.lead_h}h</> : "—"}{loading ? " · updating" : ""}
            {error && <span className="err"> · {error}</span>}
          </div>
        </header>
        <main className="view" id="main" tabIndex={-1}>
          {view === "command" && <Command />}
          {view === "why" && <Why />}
          {view === "regime" && <Regime />}
          {view === "models" && <Models />}
          {view === "autopsy" && <Autopsy />}
          {view === "lab" && <Lab />}
        </main>
      </div>
    </div>
  );
}
