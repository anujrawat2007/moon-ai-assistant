@echo off
title Lumina Avatar
cd /d "%~dp0"
call .\venv\Scripts\activate
python avatar\overlay.py

