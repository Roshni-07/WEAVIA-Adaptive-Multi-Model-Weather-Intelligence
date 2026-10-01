export type Var = "rain" | "temp" | "wind";
export const VARS: Var[] = ["rain", "temp", "wind"];
export const VAR_NAME: Record<Var, string> = { rain: "Rainfall", temp: "Temperature", wind: "Wind" };
export const VAR_UNIT: Record<Var, string> = { rain: "mm/6h", temp: "°C", wind: "km/h" };

export interface Meta {
  provenance: { data_mode: string; data_notice: string; model_version: string; generated_at: string };
  issues: string[]; latest_issue: string; leads: number[];
  variables: Record<string, { label: string; unit: string; event_threshold: number }>;
  models: { model_id: string; name: string; kind: string; label: string }[];
  regimes: string[];
  locations: { id: string; name: string; lat: number; lon: number; region: string; coastal: boolean }[];
}
export interface VarPoint { value: number | null; p10: number | null; p90: number | null; confidence: number | null; spread: number | null; event_prob: number | null }
export interface MapPoint {
  location_id: string; name: string; lat: number; lon: number; region: string; regime: string; regime_confidence: number | null;
  risk: number; risk_variable: Var | null; top_model: { model_id: string; name: string; weight: number };
  weights: Record<string, number>; vars: Record<Var, VarPoint>;
}
export interface MapOut { issue_time: string; lead_h: number; valid_time: string; units: Record<string, string>; points: MapPoint[]; weight_flow: Record<string, number> }

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api/v1${path}`, init);
  if (!r.ok) {
    let d = r.statusText;
    try { d = (await r.json()).detail ?? d; } catch {}
    throw new Error(typeof d === "string" ? d : JSON.stringify(d));
  }
  return r.json();
}
const q = (o: Record<string, string | number | undefined>) =>
  "?" + Object.entries(o).filter(([, v]) => v !== undefined).map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join("&");

export const api = {
  meta: () => req<Meta>("/meta"),
  map: (issue: string, lead: number) => req<MapOut>("/map" + q({ issue, lead })),
  overview: (issue: string, lead: number) => req<any>("/overview" + q({ issue, lead })),
  forecast: (location_id: string, variable: Var, issue: string, lead: number) => req<any>("/forecast" + q({ location_id, variable, issue, lead })),
  timeline: (location_id: string, variable: Var, issue: string) => req<any>("/timeline" + q({ location_id, variable, issue })),
  explain: (location_id: string, variable: Var, issue: string, lead: number) => req<any>("/explain" + q({ location_id, variable, issue, lead })),
  regime: (location_id: string, issue: string, lead: number) => req<any>("/regime" + q({ location_id, issue, lead })),
  skillAtlas: (variable: Var, lead: number) => req<any>("/skill-atlas" + q({ variable, lead })),
  verification: () => req<any>("/verification"),
  events: (variable?: string, limit = 60) => req<any[]>("/events" + q({ variable, limit })),
  autopsy: (id: string, lead: number) => req<any>(`/autopsy/${id}` + q({ lead })),
  lab: (body: any) => req<any>("/lab/simulate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
};
