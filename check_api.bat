@echo off
cd /d "%~dp0backend"
call .venv\Scripts\activate
python smoke_check.py
pause
