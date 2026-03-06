@echo off
title STT_SERVER (RTX 5080)

:: 프로젝트 절대 경로 설정
set BASE_DIR=C:\dev\stt_agent
set MODELSCOPE_CACHE=%BASE_DIR%\models
set XDG_CACHE_HOME=%BASE_DIR%\models
set HF_HOME=%BASE_DIR%\models

:: models 폴더 생성
if not exist "%MODELSCOPE_CACHE%" mkdir "%MODELSCOPE_CACHE%"

cd /d %BASE_DIR%

:: 가상 환경 폴더명 확인 (.venv 인지 venv 인지)
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else (
    echo [!] Virtual environment not found. Please run setup first.
    pause
    exit /b
)

echo Running FastAPI Server on Port 8000 (RTX 5080 Activated)
echo Cache Directory: %MODELSCOPE_CACHE%

uvicorn server.app.main:app --host 0.0.0.0 --port 8000
pause
