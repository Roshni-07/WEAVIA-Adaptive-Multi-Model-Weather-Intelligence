import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "./globals.css";
import type { Metadata } from "next";
import type { ReactNode } from "react";
const SITE = process.env.NEXT_PUBLIC_SITE_URL;   // set when deployed so canonical and social URLs resolve
const TITLE = "WEAVIA — adaptive multi-model weather intelligence";
const DESC = "Hybrid AI–NWP forecast blending: which weather model to trust, where, and why. Prototype on synthetic data. Smart India Hackathon 2026, SIH26081.";
export const metadata: Metadata = {
  ...(SITE ? { metadataBase: new URL(SITE) } : {}),
  title: TITLE,
  description: DESC,
  applicationName: "WEAVIA",
  keywords: ["weather forecast blending", "NWP", "AI weather models", "forecast verification", "SIH 2026", "MoES"],
  robots: { index: true, follow: true },
  openGraph: { title: TITLE, description: DESC, type: "website", siteName: "WEAVIA" },
  twitter: { card: "summary", title: TITLE, description: DESC },
};
export const viewport = { width: "device-width", initialScale: 1, themeColor: "#070b0f" };
export default function Root({ children }: { children: ReactNode }) {
  return (<html lang="en"><body>{children}</body></html>);
}
