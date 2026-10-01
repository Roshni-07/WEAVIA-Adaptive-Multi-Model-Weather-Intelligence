export const n = (x: number | null | undefined, d = 1) => { if (x === null || x === undefined || Number.isNaN(x)) return "—"; const s = x.toFixed(d); return /^-0(\.0+)?$/.test(s) ? s.slice(1) : s; };
export const pct = (x: number | null | undefined, d = 0) => (x === null || x === undefined ? "—" : (100 * x).toFixed(d) + "%");
export const nice = (s: string) => s.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
export const day = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short", timeZone: "UTC" });
export const dt = (iso: string) => new Date(iso).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }) + " UTC";
export const MODEL_COLOR: Record<string, string> = { model_a: "#d8d4c7", model_b: "#8fa6ad", model_c: "#b9a77a", model_d: "#c58f86" };
export const VAR_COLOR: Record<string, string> = { rain: "#35c3d8", temp: "#f0a63a", wind: "#a8d8a0", risk: "#ef5b3a", weights: "#d8d4c7" };
