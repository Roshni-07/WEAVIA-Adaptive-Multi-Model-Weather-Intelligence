# Hosting the demo (free tier)

Judges can open a link instead of running anything. The hosted demo serves the **synthetic benchmark snapshot** in `demo_data/` (24 MB, 60 issues of the monsoon of the synthetic run). The banner on every screen says so. It is not live forecasting.

## What gets hosted

| Part | Where | Why |
|---|---|---|
| API (FastAPI, reads `demo_data/`) | Render, free web service | Python, about 300 MB RAM measured locally |
| Frontend (Next.js) | Vercel, free hobby plan | Proxies `/api/v1/*` to the API server-side, so no CORS setup |

Free tiers **sleep when idle**. The first request after a pause can take about a minute. Say so next to the link, and keep the screenshots and video in the README as the fallback.

## Steps (about 15 minutes)

1. **API on Render**
   - New > Blueprint > pick this repo. It reads `render.yaml`. Plan: free.
   - When it is live, open `https://<your-service>.onrender.com/api/v1/health`. Expect `{"status":"ok",...}`.
2. **Frontend on Vercel**
   - New Project > import this repo. Set **Root Directory** to `weavia-frontend`.
   - Environment variable: `WEAVIA_API` = `https://<your-service>.onrender.com` (no trailing slash). It must be set **before** the build, because the proxy rule is baked in at build time.
   - Deploy. Open the Vercel URL. The banner should read SYNTHETIC DATA with the snapshot note.
3. **Add the link** to the README link row, with the cold-start note.

## Verified and not verified

- Verified locally: the lean requirements (`backend/requirements-api.txt`) install in a clean virtual environment, the API serves all 16 routes on `demo_data/` (238 requests, 0 failures), and the frontend builds.
- **Not verified:** Render and Vercel themselves. `render.yaml` follows Render's Blueprint format but has never been run on Render. If a field is rejected, the dashboard error names it.
- Rate limit is 600 requests a minute for the demo because the UI makes many calls per click. Without a trusted-proxy setting, all visitors share one bucket. That is fine for judging, not for public traffic.

## Alternatives

- **Hugging Face Spaces (Docker)**: more RAM on the free tier (check current limits), one container for API and UI. Needs a Dockerfile, which is not written yet.
- **Local, no hosting:** `scripts\run_demo.bat` (Windows) starts the API on `demo_data/` and the frontend. Untested on Windows from the development sandbox.

## Rebuilding the snapshot

```bat
cd backend
python -u -W ignore -c "from weavia.pipeline import run; run('data', days=1095)"
cd ..
python scripts\make_demo_snapshot.py backend\data demo_data --issues 60
```
The snapshot window is chosen so the landing day is wet and contains forecast-miss events. Verification figures in the snapshot summarise the **full** run. The Lab back-test and skill atlas recompute from the kept rows, so they are noisier.

## When real data works

Real-mode artifacts (`data_live/`) are not committed. To host live forecasting, run `python -m weavia.live loop` on a machine or scheduled job that writes to a place the API can read, which is a larger setup than this static demo.
