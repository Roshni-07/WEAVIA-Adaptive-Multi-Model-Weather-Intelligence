@echo off
rem One-click local demo on the committed snapshot (synthetic data). Needs Python 3.12 and Node 18+.
cd /d %~dp0..\backend
pip install -r requirements-api.txt
start "WEAVIA API" cmd /k "set WEAVIA_DATA=..\demo_data&& set WEAVIA_RATE_LIMIT=0&& python -m uvicorn weavia.api.main:app --port 8000"
cd /d %~dp0..\weavia-frontend
call npm install
call npm run dev
