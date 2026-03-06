@echo off
title STT_MASTER_CONTROL
cd /d %~dp0

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

python client_test/master_control.py
pause
