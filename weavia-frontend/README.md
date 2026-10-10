# WEAVIA frontend

Next.js 14 · TypeScript · React Three Fiber · Zustand. Consumes the FastAPI only (`/api/v1/*`, proxied by `next.config.mjs`).

## Run
```bash
# 1. backend artifacts + API
cd backend && pip install -r requirements.txt
python -u -W ignore -m weavia.pipeline          # writes data/ (~2-3 min, 3-year synthetic run: pass days=1095)
uvicorn weavia.api.main:app --port 8000
# 2. frontend
cd ../weavia-frontend && npm install && npm run dev      # http://localhost:3000
# WEAVIA_API=http://host:8000 to point elsewhere
```
State lives in the URL (`?view=&loc=&var=&lead=&issue=`), so every screen is deep-linkable.

## Screens
Command Center (globe + forecast + trust bar + timeline) · Why This Forecast · Regimes · Models & Skill · Autopsy · Lab.
