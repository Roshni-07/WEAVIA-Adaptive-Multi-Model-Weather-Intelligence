# WEAVIA frontend session: work log (Oct 1, 2026)

## Done
1. Backend stabilised: deps installed, `weavia.pipeline` imports, full run completes (3-year synthetic data, ~135 s). Earlier "death" was the sandbox killing background jobs at tool-call end, not a crash. store/explain/autopsy/lab now executed on real artifacts, all pass.
2. FastAPI `weavia/api/main.py`: /health /meta /map /overview /forecast /timeline /trust /regime /explain /skill-atlas /verification /events /autopsy/{id} /lab/simulate. Store-only reads, pydantic models on meta/map, 422/404 validation, CORS.
3. `tests/test_api.py`: 6 passing (weights sum to 1, p10<=p50<=p90, validation errors, lab identity, autopsy round trip).
4. Fix in explain.py: narrative grammar ("because it largest verified error") and honest fallback when no model stands out.
5. Frontend (`weavia-frontend/`): 6 screens, builds clean, typechecks, headless-Chrome tested, zero console errors.
   - Globe: real data only. Field layers (rain, temp, wind speed, event risk) are IDW-interpolated from the 20 station values returned by /map, clipped to India, faded far from stations. Model-trust layer colours stations by top model. Red rings = stations above the calibrated alert threshold. Model-weight flow: 4 model nodes feed the selected station, line width/speed scale with weight.
   - Wind particles NOT drawn: API has no wind direction; inventing it would be fake data. Needs direction in the pipeline.
   - Command Center, Why (10-step chain + per-model evidence), Regimes, Models & Skill (atlas + bootstrap verdicts + coverage + events), Autopsy, Lab (live back-test).
   - Synthetic-data banner always visible; "CI includes 0: no claim" and "too few events" shown instead of skill claims.
   - /web-design-guidelines run: added skip link, `<main>`, heading hierarchy, color-scheme, focus/hover states, reduced-motion in JS animation, URL state sync, translate=no on brand, keyboard location select (globe is mouse-only), content-visibility on long list.

## Honest caveats
- Synthetic data only. Numbers validate machinery, not real skill.
- Rain P10-P90 intervals are almost zero width when forecast is ~0 and in autopsy events (observed 98 mm vs band 26.47-26.61). Coverage 71-79% vs 80% nominal. Uncertainty calibration for rain needs work (heavy-tailed, quantile-based).
- Confidence is ~0.99 mean for rain vs 0.95 realised (over-confident, poorly spread).
- Temperature events: no event model (too few events); UI shows n/a.
- Default issue is the latest test date; layers look empty on dry days. Use the issue slider; a "jump to most active day" control is a good next add.
- Weight reasons for dry cases (all errors 0.00) are noise ("smallest error 0.00"); suppress when MAE ~0.
- Not built: R3F rain/temp as time animation, MapLibre, DB/docker, real Open-Meteo provider, motion polish, no pushed repo (sandbox cannot push).

## Next
1. Fix rain interval calibration (conformal/quantile on log1p), re-check confidence spread.
2. Add wind u/v to synthetic world + providers, then wind particles on globe.
3. openmeteo.py provider; db/schema.sql + docker-compose.
