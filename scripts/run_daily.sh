#!/usr/bin/env bash
# macOS/Linux: cron 에서 하루 한 번 실행. 수집 코드(collector.run)가 완성된 뒤에 사용합니다.
# 예) crontab -e 에  10 9 * * * /경로/AI-agent/scripts/run_daily.sh
cd "$(dirname "$0")/.." || exit 1
mkdir -p data/logs
python -m collector.run >> data/logs/cron.log 2>&1
