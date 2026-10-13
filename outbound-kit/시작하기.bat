@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 (
    powershell.exe -NoProfile -File "%~dp0bootstrap.ps1"
) else (
    py -3 "%~dp0start.py"
)
if errorlevel 1 (
    echo 설치를 여기서 멈췄습니다. 화면의 안내를 확인하고 다시 실행해 주세요.
    pause
)
