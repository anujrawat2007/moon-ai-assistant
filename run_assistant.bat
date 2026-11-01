@echo off
title MOON - AI Web Companion & Assistant
cd /d "%~dp0"
echo Starting MOON Web Companion...
call .\venv\Scripts\activate
python app.py
pause
