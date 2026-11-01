@echo off
title Moon - AI Desktop Companion
cd /d "%~dp0"
call .\venv\Scripts\activate
python main.py
pause
