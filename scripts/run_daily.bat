@echo off
REM Windows 작업 스케줄러에서 하루 한 번 실행하도록 등록하세요. (docs/runbook.md 참고)
REM 수집 코드(collector.run)가 완성된 뒤에 사용합니다.
cd /d "%~dp0.."
if not exist data\logs mkdir data\logs
python -m collector.run >> data\logs\cron.log 2>&1
