@echo off
cd /d %~dp0
set PYTHONUNBUFFERED=1
python -u main_gui.py
