@echo off
title Moon Assistant - Audio & Mic Test
cd /d "%~dp0"
call .\venv\Scripts\activate
python test_audio.py
pause

