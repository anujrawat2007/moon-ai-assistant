@echo off
title Moon AI Assistant (Lumina)
cd /d "%~dp0"
echo Starting Moon AI Assistant...
call .\venv\Scripts\activate
python main.py
pause

