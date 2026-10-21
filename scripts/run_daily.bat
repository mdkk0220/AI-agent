@echo off
REM Windows 작업 스케줄러에서 하루 한 번 실행하도록 등록합니다.
REM 가상환경(.venv)의 파이썬을 직접 지정하므로, 활성화 없이도 패키지를 찾을 수 있습니다.
cd /d "%~dp0.."
if not exist data\logs mkdir data\logs
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m collector.run >> data\logs\cron.log 2>&1
) else (
    python -m collector.run >> data\logs\cron.log 2>&1
)