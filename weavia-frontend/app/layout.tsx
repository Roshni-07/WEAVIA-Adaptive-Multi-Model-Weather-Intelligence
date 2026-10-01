import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "./globals.css";
import type { ReactNode } from "react";
export const metadata = { title: "WEAVIA — adaptive multi-model weather intelligence", description: "Which model to trust, where, and why." };
export const viewport = { width: "device-width", initialScale: 1, themeColor: "#070b0f" };
export default function Root({ children }: { children: ReactNode }) {
  return (<html lang="en"><body>{children}</body></html>);
}
