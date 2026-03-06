@echo off
title STT_SYSTEM_MASTER_LAUNCHER
cd /d %~dp0

:: 가상 환경 활성화 및 제어판 실행
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

echo Starting RTX 5080 STT Master System...
echo (Server will run in the background)

:: 콘솔 창 없이 GUI만 실행하기 위해 pythonw 대신 python 사용 (로그 확인용)
python client_test/master_control.py

pause
