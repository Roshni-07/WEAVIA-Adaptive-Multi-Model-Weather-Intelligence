export const n = (x: number | null | undefined, d = 1) => { if (x === null || x === undefined || Number.isNaN(x)) return "—"; const s = x.toFixed(d); return /^-0(\.0+)?$/.test(s) ? s.slice(1) : s; };
export const pct = (x: number | null | undefined, d = 0) => (x === null || x === undefined ? "—" : (100 * x).toFixed(d) + "%");
export const nice = (s: string) => s.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
export const day = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short", timeZone: "UTC" });
export const dt = (iso: string) => new Date(iso).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }) + " UTC";
export const issueLabel = (s: string) => (s.includes("T") ? dt(s) : day(s));      // real-data issues are 6-hourly: show the hour
export const ago = (min: number | null) => (min == null ? "unknown" : min < 90 ? `${Math.round(min)} min ago` : min < 2880 ? `${(min / 60).toFixed(1)} h ago` : `${Math.round(min / 1440)} d ago`);
const MODEL_COLORS = ["#d8d4c7", "#8fa6ad", "#b9a77a", "#c58f86"];
export const MODEL_COLOR: Record<string, string> = {
  model_a: MODEL_COLORS[0], model_b: MODEL_COLORS[1], model_c: MODEL_COLORS[2], model_d: MODEL_COLORS[3],
  ifs: MODEL_COLORS[0], aifs: MODEL_COLORS[1], gfs: MODEL_COLORS[2], icon: MODEL_COLORS[3],      // real-data model ids
};
export const VAR_COLOR: Record<string, string> = { rain: "#35c3d8", temp: "#f0a63a", wind: "#a8d8a0", risk: "#ef5b3a", weights: "#d8d4c7" };
