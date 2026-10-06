import { create } from "zustand";
import { api, Meta, MapOut, Var } from "./api";

export type View = "command" | "why" | "regime" | "extremes" | "models" | "autopsy" | "lab";
export type Layer = "rain" | "temp" | "wind" | "risk" | "weights";

interface S {
  view: View; meta?: Meta; map?: MapOut; overview?: any; error?: string; loading: boolean;
  issue: string; lead: number; variable: Var; layer: Layer; locationId: string;
  setView: (v: View) => void; setIssue: (i: string) => void; setLead: (l: number) => void;
  setVariable: (v: Var) => void; setLayer: (l: Layer) => void; select: (id: string) => void;
  boot: () => Promise<void>; refresh: () => Promise<void>;
}
export const useW = create<S>((set, get) => ({
  view: "command", loading: true, issue: "", lead: 24, variable: "rain", layer: "rain", locationId: "maa",
  setView: (view) => set({ view }),
  setIssue: (issue) => { set({ issue }); get().refresh(); },
  setLead: (lead) => { set({ lead }); get().refresh(); },
  setVariable: (variable) => set({ variable, layer: variable }),
  setLayer: (layer) => set((s) => ({ layer, variable: layer === "rain" || layer === "temp" || layer === "wind" ? layer : s.variable })),
  select: (locationId) => set({ locationId }),
  boot: async () => {
    try {
      const meta = await api.meta();
      const q = typeof window === "undefined" ? new URLSearchParams() : new URLSearchParams(window.location.search);
      const pick = <T extends string | number>(v: string | null, ok: T[], d: T): T => { const c = (typeof ok[0] === "number" ? Number(v) : v) as T; return ok.includes(c) ? c : d; };
      const issue = meta.issues.includes(q.get("issue") ?? "") ? q.get("issue")! : meta.latest_issue;
      const variable = pick<Var>(q.get("var"), ["rain", "temp", "wind"], "rain");
      set({ meta, issue, variable, layer: variable, lead: pick(q.get("lead"), meta.leads, 24),
            locationId: meta.locations.some((l) => l.id === q.get("loc")) ? q.get("loc")! : "maa",
            view: pick<View>(q.get("view"), ["command", "why", "regime", "extremes", "models", "autopsy", "lab"], "command") });
      await get().refresh();
    } catch (e: any) { set({ error: e.message, loading: false }); }
  },
  refresh: async () => {
    const { issue, lead } = get();
    if (!issue) return;
    set({ loading: true });
    try {
      const [map, overview] = await Promise.all([api.map(issue, lead), api.overview(issue, lead)]);
      if (get().issue === issue && get().lead === lead) set({ map, overview, loading: false, error: undefined });
    } catch (e: any) { set({ error: e.message, loading: false }); }
  },
}));

/** URL reflects state so views are deep-linkable and shareable. */
if (typeof window !== "undefined") {
  useW.subscribe((s) => {
    if (!s.meta) return;
    const q = new URLSearchParams({ view: s.view, loc: s.locationId, var: s.variable, lead: String(s.lead), issue: s.issue });
    window.history.replaceState(null, "", "?" + q.toString());
  });
}
