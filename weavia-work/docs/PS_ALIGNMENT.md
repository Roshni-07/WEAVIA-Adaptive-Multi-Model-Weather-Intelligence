# SIH26081 Alignment Matrix

**Smart India Hackathon 2026 · SIH26081 · Hybrid AI–NWP Multi-Model Forecast Blending System · MoES (NCMRWF)**

Source: the problem statement text on sih.gov.in. Status legend: 🟢 done and evidenced · 🟡 built, evidence incomplete · 🔴 gap.

## Inputs the PS names

| PS wording | Status | Evidence and gap |
|---|---|---|
| Physical NWP models | 🟡 | Real: ECMWF IFS, NOAA GFS, DWD ICON via Open-Meteo (built, not yet run on the real service) |
| AI/ML weather models | 🟡 | Real: ECMWF AIFS via Open-Meteo (same caveat) |
| Ensemble forecasts | 🔴 | Real mode has none. Synthetic mode has an ensemble-kind source. Back-filling real ensembles needs a history source, which Open-Meteo Previous Runs may not offer. Option: archive live ensemble members every cycle and train after enough history |
| Weights from historical skill, lead time, region, season, weather regime | 🟢 | Trust engine uses all five. Works for 3 or more sources (tested) |

## Expected outcomes

| PS outcome | Status | Evidence | Remaining work |
|---|---|---|---|
| Dynamically blended forecast | 🟡 | 119 tests, synthetic verification | Real-data run |
| Model weight maps (region, lead time) | 🟡 | `/map`, `/trust`, globe, skill atlas | 20 stations interpolated, not gridded. No export yet |
| Improved skill vs individual models | 🟡 | Bootstrap CIs on synthetic data | Real-data verification, independent truth |
| Heavy rainfall guidance | 🟡 | IMD-day (24 h) totals from hourly data, IMD classes, calibrated heavy-rain probability, verification with date-block CIs, `/extremes` and the Extremes view. Tested offline | Run on real data. Few heavy-rain events may mean no claim is possible |
| Heat-wave guidance | 🟡 | IST-day maximum, reanalysis normals per station, IMD rule (terrain gate, departure, 45/47 °C, regional 2-station 2-day persistence), probability, CIs on event skill, `/extremes` and the Extremes view. Tested offline | Run on real data. Confirm terrain classes. Normals are reanalysis-based, not IMD's |
| High-wind guidance | 🟡 | Configurable proxy (30 km/h sustained) | No single IMD value found. Confirm with IMD and source it |
| Operational workflow (script/dashboard, routine blending) | 🟡 | `weavia.live fit/cycle/loop`, API reload, freshness banner, offline end-to-end tests | First real `check`, `fit`, `cycle` |

## Known departures from IMD practice

- Heat-wave output is an **indicator**. Only IMD declares heat waves.
- Station terrain classes (plains, coastal, hilly) are **proposed** from coordinates. Confirm them.
- IMD's persistence rule uses a meteorological sub-division. WEAVIA has 20 stations grouped into 6 coarse regions, so it applies the rule per region.
- IMD's rainfall day runs 08:30 to 08:30 IST. WEAVIA's 6-hourly UTC grid approximates it.

## Priority plan

| P | Item | Needs from you |
|---|---|---|
| P0 | Real-data run: `check`, `fit`, `cycle` | Run on a machine with internet and paste `check` output |
| P0 | IMD-aligned events wired in (daily Tmax, normals, 24-hour rain) | Confirm station terrain classes |
| P0 | Ensemble source | Decide: archive-and-wait, or frame ensemble as spread-based uncertainty |
| P1 | Independent truth (IMD gridded rain, GPM IMERG) | IMD data request, NASA Earthdata login (free) |
| P1 | CIs on event metrics, weight-map export | none |
| P2 | Deployment recipe, README wording | A hosting account (free tier) |
