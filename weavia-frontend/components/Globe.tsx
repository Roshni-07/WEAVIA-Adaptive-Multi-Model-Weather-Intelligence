"use client";
import { useMemo, useRef, useState, useEffect } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls, Html, Line } from "@react-three/drei";
import * as THREE from "three";
import { feature, mesh } from "topojson-client";
import world from "world-atlas/countries-110m.json";
import { MapOut, MapPoint, Var } from "@/lib/api";
import { Layer } from "@/lib/store";
import { MODEL_COLOR, VAR_COLOR } from "@/lib/format";

const R = 1;
const B = { lon0: 62, lon1: 100, lat0: 4, lat1: 38 };
const rad = (d: number) => (d * Math.PI) / 180;
export const ll2v = (lat: number, lon: number, r = R) => {
  const p = rad(90 - lat), t = rad(lon + 180);
  return new THREE.Vector3(-r * Math.sin(p) * Math.cos(t), r * Math.cos(p), r * Math.sin(p) * Math.sin(t));
};

/* ---- colour ramps & layer scaling (shared with the legend) ---- */
const hex = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const RAMPS: Record<string, string[]> = {
  rain: ["#0a2630", "#1d7f93", "#35c3d8", "#e4fbff"], temp: ["#2b2214", "#8a5a1c", "#f0a63a", "#ff6a2a"],
  wind: ["#15241a", "#5f8f63", "#a8d8a0", "#f2ffec"], risk: ["#2a0f0a", "#b8321c", "#ef5b3a", "#ffd2a0"],
};
function ramp(name: string, t: number) {
  const s = RAMPS[name].map(hex), x = Math.min(0.9999, Math.max(0, t)) * (s.length - 1), i = Math.floor(x), f = x - i;
  return s[i].map((c, k) => c + (s[i + 1][k] - c) * f);
}
export const SCALE: Record<string, { lo: number; hi: number; unit: string; norm: (v: number) => number }> = {
  rain: { lo: 0, hi: 40, unit: "mm/6h", norm: (v) => Math.log1p(Math.max(0, v)) / Math.log1p(40) },
  temp: { lo: 10, hi: 42, unit: "°C", norm: (v) => (v - 10) / 32 },
  wind: { lo: 0, hi: 40, unit: "km/h", norm: (v) => v / 40 },
  risk: { lo: 0, hi: 1, unit: "P(event)", norm: (v) => v },
};
export const rampCss = (l: string) => `linear-gradient(90deg, ${RAMPS[l]?.join(",")})`;

function value(p: MapPoint, layer: string): number {
  if (layer === "risk") return p.risk;
  return p.vars[layer as Var]?.value ?? 0;
}

/* ---- interpolated field (IDW from the stations, clipped to India, faded far from any station) ---- */
const india: any = (feature(world as any, (world as any).objects.countries) as any).features.find((f: any) => String(f.id) === "356");
function buildField(points: MapPoint[], layer: string) {
  const W = 304, H = 272, c = document.createElement("canvas");
  c.width = W; c.height = H;
  const g = c.getContext("2d")!, img = g.createImageData(W, H), sc = SCALE[layer];
  const vals = points.map((p) => value(p, layer));
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const lon = B.lon0 + ((x + 0.5) / W) * (B.lon1 - B.lon0), lat = B.lat1 - ((y + 0.5) / H) * (B.lat1 - B.lat0);
    let ws = 0, vs = 0, dmin = 99;
    for (let k = 0; k < points.length; k++) {
      const dx = (lon - points[k].lon) * Math.cos(rad(lat)), dy = lat - points[k].lat, d2 = dx * dx + dy * dy + 0.05;
      const w = 1 / Math.pow(d2, 1.25);
      ws += w; vs += w * vals[k]; if (d2 < dmin) dmin = d2;
    }
    const t = Math.min(1, Math.max(0, sc.norm(vs / ws))), [r, gg, b] = ramp(layer, t);
    const fade = Math.min(1, Math.max(0, 1 - (Math.sqrt(dmin) - 2.2) / 3));
    const i = (y * W + x) * 4;
    img.data[i] = r; img.data[i + 1] = gg; img.data[i + 2] = b; img.data[i + 3] = 255 * fade * (0.25 + 0.7 * t);
  }
  g.putImageData(img, 0, 0);
  g.globalCompositeOperation = "destination-in";
  g.beginPath();
  const polys = india.geometry.type === "Polygon" ? [india.geometry.coordinates] : india.geometry.coordinates;
  for (const poly of polys) for (const ring of poly) ring.forEach(([lo, la]: number[], i: number) => {
    const px = ((lo - B.lon0) / (B.lon1 - B.lon0)) * W, py = ((B.lat1 - la) / (B.lat1 - B.lat0)) * H;
    i ? g.lineTo(px, py) : g.moveTo(px, py);
  });
  g.fill();
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 4;
  return tex;
}

function FieldPatch({ map, layer }: { map: MapOut; layer: string }) {
  const tex = useMemo(() => (SCALE[layer] ? buildField(map.points, layer) : null), [map, layer]);
  if (!tex) return null;
  return (
    <mesh>
      <sphereGeometry args={[R * 1.002, 96, 96, rad(B.lon0 + 180), rad(B.lon1 - B.lon0), rad(90 - B.lat1), rad(B.lat1 - B.lat0)]} />
      <meshBasicMaterial map={tex} transparent depthWrite={false} side={THREE.FrontSide} />
    </mesh>
  );
}

/* ---- static geography: graticule, coastlines, borders ---- */
function densify(line: number[][], out: number[], r: number) {
  for (let i = 0; i < line.length - 1; i++) {
    const [a, b] = [line[i], line[i + 1]], n = Math.max(1, Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / 1.5));
    for (let k = 0; k < n; k++) {
      const p = ll2v(a[1] + ((b[1] - a[1]) * k) / n, a[0] + ((b[0] - a[0]) * k) / n, r), q = ll2v(a[1] + ((b[1] - a[1]) * (k + 1)) / n, a[0] + ((b[0] - a[0]) * (k + 1)) / n, r);
      out.push(p.x, p.y, p.z, q.x, q.y, q.z);
    }
  }
}
function Geo() {
  const { coast, border, grat } = useMemo(() => {
    const w: any = world, coast: number[] = [], border: number[] = [], grat: number[] = [];
    const land: any = mesh(w, w.objects.land), brd: any = mesh(w, w.objects.countries, (a: any, b: any) => a !== b);
    land.coordinates.forEach((l: number[][]) => densify(l, coast, R * 1.001));
    brd.coordinates.forEach((l: number[][]) => densify(l, border, R * 1.001));
    for (let lat = -80; lat <= 80; lat += 10) { const l: number[][] = []; for (let lo = -180; lo <= 180; lo += 5) l.push([lo, lat]); densify(l, grat, R * 1.0005); }
    for (let lo = -180; lo < 180; lo += 10) { const l: number[][] = []; for (let la = -85; la <= 85; la += 5) l.push([lo, la]); densify(l, grat, R * 1.0005); }
    return { coast: new Float32Array(coast), border: new Float32Array(border), grat: new Float32Array(grat) };
  }, []);
  const seg = (a: Float32Array, color: string, op: number) => (
    <lineSegments><bufferGeometry><bufferAttribute attach="attributes-position" array={a} count={a.length / 3} itemSize={3} /></bufferGeometry>
      <lineBasicMaterial color={color} transparent opacity={op} /></lineSegments>
  );
  return <>{seg(grat, "#22303b", 0.55)}{seg(border, "#4a5f6b", 0.7)}{seg(coast, "#7c97a5", 0.95)}</>;
}

/* ---- markers, hotspots ---- */
function Disc({ at, r, color, op = 1, ring = false, inner = 0.8 }: { at: THREE.Vector3; r: number; color: string; op?: number; ring?: boolean; inner?: number }) {
  const q = useMemo(() => new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 0, 1), at.clone().normalize()), [at]);
  return (
    <mesh position={at} quaternion={q} renderOrder={5}>
      {ring ? <ringGeometry args={[r * inner, r, 40]} /> : <circleGeometry args={[r, 24]} />}
      <meshBasicMaterial color={color} transparent opacity={op} depthWrite={false} side={THREE.DoubleSide} />
    </mesh>
  );
}

function Markers({ map, layer, selected, onSelect, thr }: { map: MapOut; layer: Layer; selected: string; onSelect: (id: string) => void; thr: Record<string, number> }) {
  const [hover, setHover] = useState<string | null>(null);
  return (
    <>
      {map.points.map((p) => {
        const at = ll2v(p.lat, p.lon, R * 1.004), sel = p.location_id === selected;
        const color = layer === "weights" ? MODEL_COLOR[p.top_model.model_id] : "#f4f1e8";
        const size = layer === "weights" ? 0.009 + 0.012 * p.top_model.weight : 0.009;
        const hot = p.risk_variable && p.risk >= (thr[p.risk_variable] ?? 1.1);
        return (
          <group key={p.location_id}>
            {hot && <Disc at={at} r={0.03 + 0.04 * p.risk} color="#ef5b3a" ring op={0.95} inner={0.72} />}
            <Disc at={at} r={size} color={color} />
            {sel && <Disc at={at} r={0.026} color="#ffffff" ring op={1} inner={0.85} />}
            <mesh position={at} onClick={(e) => { e.stopPropagation(); onSelect(p.location_id); }}
              onPointerOver={(e) => { e.stopPropagation(); setHover(p.location_id); document.body.style.cursor = "pointer"; }}
              onPointerOut={() => { setHover(null); document.body.style.cursor = ""; }}>
              <sphereGeometry args={[0.03, 8, 8]} /><meshBasicMaterial transparent opacity={0} depthWrite={false} />
            </mesh>
            {(sel || hover === p.location_id) && (
              <Html position={at} style={{ pointerEvents: "none" }} zIndexRange={[20, 0]} occlude={false}>
                <div className="gtag">{p.name}</div>
              </Html>
            )}
          </group>
        );
      })}
    </>
  );
}

/* ---- model-weight flow: four model nodes feed the selected station; width & speed scale with trust weight ---- */
function Flow({ map, selected }: { map: MapOut; selected: string }) {
  const p = map.points.find((x) => x.location_id === selected);
  const refs = useRef<any[]>([]);
  const geo = useMemo(() => {
    if (!p) return [];
    const n = ll2v(p.lat, p.lon, 1).normalize(), side = new THREE.Vector3().crossVectors(n, new THREE.Vector3(0, 1, 0)).normalize();
    const to = ll2v(p.lat, p.lon, R * 1.006);
    return Object.keys(p.weights).map((m, i) => {
      const node = n.clone().multiplyScalar(1.5).add(side.clone().multiplyScalar((i - 1.5) * 0.24));
      const mid = to.clone().add(node).multiplyScalar(0.5).normalize().multiplyScalar(1.28).add(side.clone().multiplyScalar((i - 1.5) * 0.06));
      return { m, node, pts: new THREE.QuadraticBezierCurve3(node, mid, to).getPoints(28), w: p.weights[m] };
    });
  }, [p]);
  const still = useMemo(() => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches, []);
  useFrame((_, dt) => { if (still) return; refs.current.forEach((l, i) => { if (l?.material && geo[i]) l.material.dashOffset -= dt * (0.15 + geo[i].w * 1.6); }); });
  if (!p) return null;
  return (
    <>
      {geo.map((g, i) => (
        <group key={g.m}>
          <Line ref={(r: any) => (refs.current[i] = r)} points={g.pts} color={MODEL_COLOR[g.m]} lineWidth={0.6 + g.w * 7} dashed dashSize={0.05} gapSize={0.035} transparent opacity={0.35 + 0.65 * g.w} />
          <Html position={g.node} center zIndexRange={[15, 0]} style={{ pointerEvents: "none" }}>
            <div className="mnode" style={{ borderColor: MODEL_COLOR[g.m], color: MODEL_COLOR[g.m] }}>{g.m.slice(-1).toUpperCase()} <b>{Math.round(g.w * 100)}</b></div>
          </Html>
        </group>
      ))}
    </>
  );
}

export default function Globe({ map, layer, selected, onSelect, thr }: { map: MapOut; layer: Layer; selected: string; onSelect: (id: string) => void; thr: Record<string, number> }) {
  const cam = useMemo(() => ll2v(21, 79, 3.3).toArray() as [number, number, number], []);
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);
  if (!ready) return null;
  return (
    <Canvas camera={{ position: cam, fov: 32, near: 0.1, far: 20 }} dpr={[1, 2]} gl={{ antialias: true }}>
      <color attach="background" args={["#070b0f"]} />
      <mesh><sphereGeometry args={[R, 96, 96]} /><meshBasicMaterial color="#0b1218" /></mesh>
      <Geo />
      <FieldPatch map={map} layer={layer} />
      <Markers map={map} layer={layer} selected={selected} onSelect={onSelect} thr={thr} />
      <Flow map={map} selected={selected} />
      <OrbitControls enablePan={false} enableDamping rotateSpeed={0.45} minDistance={1.7} maxDistance={4.5} />
    </Canvas>
  );
}
