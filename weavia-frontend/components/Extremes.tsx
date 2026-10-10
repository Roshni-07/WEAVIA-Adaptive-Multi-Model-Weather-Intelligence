"use client";
import { useState } from "react";
import { useW } from "@/lib/store";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { n, pct, nice } from "@/lib/format";
import { Panel, Err } from "./ui";

const HW = ["no heat wave", "heat wave", "severe heat wave"];

export default function Extremes() {
  const { issue, select, locationId } = useW();
  const [day, setDay] = useState(1);
  const { data: d, error } = useApi(() => api.extremes("", day), [day, issue], true);
  const { data: v } = useApi(() => api.extremesVerification(), [], true);
  const hwv = v?.verification?.heat_wave?.[String(day)];
  const rv = v?.verification?.heavy_rain?.[String(day)];
  const gain = hwv?.f1_gain_vs_equal;
  const msg = error ? String((error as any).message ?? error) : "";
  if (msg.includes("No daily extremes")) {        // synthetic demo: say so plainly instead of showing empty panels and a raw error
    const doc = (f: string) => `https://github.com/Roshni-07/WEAVIA-Adaptive-Multi-Model-Weather-Intelligence/blob/main/docs/${f}`;
    return (
      <div className="page">
        <div className="bar"><h1>Extreme-weather guidance</h1></div>
        <Panel title="Not available in this demo" sub="this hosted copy runs on the synthetic benchmark">
          <p className="defn">Heat-wave and heavy-rain guidance follow IMD criteria: terrain-specific heat-wave thresholds with departure from the station normal and a 2-station, 2-day persistence rule, plus IMD 24-hour rainfall classes. They are computed in real-data mode from Open-Meteo forecasts, which this demo does not run.</p>
          <p className="defn">This demo serves synthetic data, so there is nothing real to show here, and nothing is faked. The rules, calibration and verification with confidence intervals are implemented and tested in the repository.</p>
          <p className="defn">
            <a href={doc("PS_ALIGNMENT.md")} target="_blank" rel="noopener noreferrer">PS alignment matrix</a>{" · "}
            <a href={doc("REAL_DATA_PLAN.md")} target="_blank" rel="noopener noreferrer">Real-data plan</a>{" · "}
            <a href={doc("VERIFICATION.md")} target="_blank" rel="noopener noreferrer">Verification</a>
          </p>
        </Panel>
      </div>
    );
  }
  return (
    <div className="page">
      <div className="bar"><h1>Extreme-weather guidance</h1>
        <div className="seg" role="group" aria-label="Lead day">{[1, 2, 3].map((k) => (
          <button key={k} className={k === day ? "on" : ""} aria-pressed={k === day} onClick={() => setDay(k)}>Day {k}</button>))}</div></div>
      <Err e={error} />
      {d && <p className="defn">{d.status} Issue {d.issue_time}, valid day {d.valid_day}. Heat-wave rule: IMD terrain gate, departure from the station normal, 45/47 °C absolute. Rain classes: IMD 24-hour totals.</p>}
      <div className="two">
        <Panel title="Heat-wave indicator" sub="stations ranked by probability, daily maximum vs normal">
          {d?.stations.map((s: any) => s.tmax && (
            <button key={s.location_id} className={"erow" + (s.location_id === locationId ? " on" : "")} onClick={() => select(s.location_id)}>
              <b>{s.name}</b><span className="dim">{nice(s.terrain)}</span>
              <span className="mono">{n(s.tmax.blend, 1)}° <i className="dim">(normal {n(s.tmax.normal, 1)}°{s.tmax.departure != null ? `, ${s.tmax.departure >= 0 ? "+" : ""}${n(s.tmax.departure, 1)}` : ""})</i></span>
              <span className="mono">{pct(s.tmax.p_heat_wave)}</span>
              <span className={"tag" + (s.tmax.heat_wave_class ? " hot" : "")}>{HW[s.tmax.heat_wave_class ?? 0]}</span>
            </button>))}
        </Panel>
        <Panel title="Rainfall, IMD 24-hour classes" sub="heavy rain is 64.5 mm or more in 24 h">
          {d?.stations.filter((s: any) => s.rain24).sort((a: any, b: any) => b.rain24.p_heavy - a.rain24.p_heavy).map((s: any) => (
            <button key={s.location_id} className={"erow" + (s.location_id === locationId ? " on" : "")} onClick={() => select(s.location_id)}>
              <b>{s.name}</b><span className="dim">{nice(s.rain24.imd_class)}</span>
              <span className="mono">{n(s.rain24.blend, 1)} mm <i className="dim">({n(s.rain24.p10, 0)}–{n(s.rain24.p90, 0)})</i></span>
              <span className="mono">{pct(s.rain24.p_heavy)}</span><span className="dim">heavy</span>
            </button>))}
        </Panel>
        <Panel title="Regional heat-wave outlook" sub="IMD persistence rule: 2+ stations on 2 consecutive days">
          {d?.regional_outlook?.length ? d.regional_outlook.map((r: any) => (
            <p key={r.region + r.date} className="defn mono">{nice(r.region)} · {r.date} · {r.stations_meeting_criterion} station(s) {r.declared_indicator ? "· heat-wave indicator" : ""}{r.severe_indicator ? " · severe" : ""}</p>
          )) : <p className="defn">No region meets the criterion in this forecast.</p>}
          <p className="defn">Groups are WEAVIA regions, not IMD sub-divisions. Only IMD declares heat waves.</p>
        </Panel>
        <Panel title="Verified evidence" sub={`held-out days, lead day ${day}`}>
          {hwv ? (
            <p className="defn mono">Heat wave: {hwv.n_obs_events} observed station-days over {hwv.n_event_days} days. {hwv.insufficient_events ? "Too few events for any claim." : gain ? `F1 gain over equal ensemble ${n(gain.value, 2)} (95% CI ${n(gain.ci95[0], 2)} to ${n(gain.ci95[1], 2)}) ${gain.significant ? "" : "— CI includes 0: no claim"}` : ""}</p>
          ) : <p className="defn">No heat-wave verification for this lead yet.</p>}
          {rv && <p className="defn mono">Heavy rain: {rv.n_obs_events} observed station-days. {rv.insufficient_events ? "Too few events for any claim." : ""}</p>}
          {v?.verification?.mae?.filter((m: any) => m.lead_day === day).map((m: any) => (
            <p key={m.variable} className="defn mono">{m.variable === "tmax" ? "Daily max temp" : "24 h rain"}: MAE vs equal ensemble {n(m.vs.equal.improvement_pct, 1)}% (CI {n(m.vs.equal.ci95_pct[0], 1)} to {n(m.vs.equal.ci95_pct[1], 1)}){m.vs.equal.significant ? "" : " — no claim"}</p>))}
        </Panel>
      </div>
    </div>
  );
}
