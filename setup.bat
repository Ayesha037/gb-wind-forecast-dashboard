@echo off
echo === Backend setup ===
cd /d "%~dp0backend"
if not exist .venv python -m venv .venv
call .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q
if not exist ..\data\snapshot.json (
  echo === Fetching January 2026 data from Elexon - takes 1 to 3 minutes ===
  python -c "from app import core; core.save_snapshot(core.fetch_live())"
)
if exist ..\data\snapshot.json (echo Snapshot OK) else (echo SNAPSHOT MISSING - check internet and rerun)
echo === Frontend setup ===
cd /d "%~dp0frontend"
call npm install
echo.
echo Setup finished. Next: double-click start_all.bat
pause
