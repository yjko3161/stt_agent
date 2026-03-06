@echo off
title SUBTITLE_GUI (RTX 5080 Client)
cd /d %~dp0

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

python client_test/gui_subtitle.py
pause
