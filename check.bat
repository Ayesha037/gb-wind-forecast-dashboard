@echo off
echo === 1/2 Backend unit tests ===
cd /d "%~dp0backend"
call .venv\Scripts\activate
python -m pytest -q
echo.
echo === 2/2 Frontend production build ===
cd /d "%~dp0frontend"
call npm run build
echo.
echo Done. Now run start_all.bat, wait 15 seconds, then run check_api.bat
pause
