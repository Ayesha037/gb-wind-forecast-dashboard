@echo off
start "backend" cmd /k "%~dp0start_backend.bat"
start "frontend" cmd /k "%~dp0start_frontend.bat"
timeout /t 8 >nul
start http://localhost:5173
