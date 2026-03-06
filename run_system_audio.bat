@echo off
title SYSTEM_AUDIO_STREAM (RTX 5080 Client)
cd /d %~dp0

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

python client_test/system_audio_test.py
pause
