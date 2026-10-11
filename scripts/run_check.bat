@echo off
rem Confirms the Open-Meteo model ids and endpoints. Needs internet. Saves the result to check_output.txt in the repo root.
cd /d %~dp0..\backend
pip install -r requirements.txt
findstr /x /c:"check_output.txt" ..\.gitignore >nul 2>&1 || echo check_output.txt>> ..\.gitignore
python -W ignore -m weavia.live check > ..\check_output.txt 2>&1
type ..\check_output.txt
echo.
echo ----------------------------------------------------------------------
echo Saved to check_output.txt in the repo root. Open it and paste its text into the chat.
pause
