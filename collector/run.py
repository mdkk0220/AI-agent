"""하루 1회 실행하는 수집기.

    python -m collector.run

종료 코드: 0 정상(일부 실패 포함, 경고 로그 확인), 1 실패, 2 키/설정 문제
"""
import argparse
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

from . import rocketpunch, storage

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("collector")


@dataclass
class RunResult:
    run_id: int = 0
    status: str = "success"
    requests: int = 0
    fetched: int = 0
    new: int = 0
    updated: int = 0
    details: int = 0          # 이번에 본문을 받은 공고 수
    error: str = ""
    auth_failed: bool = False

MAX_CONSECUTIVE_DETAIL_FAILS = 5  # 본문 요청이 연속으로 이만큼 실패하면 서버 문제로 보고 중단


def load_config(path: str | None = None) -> dict:
    with open(path or ROOT / "collector" / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def collect(conn, client, cfg: dict) -> RunResult:
    run_id = storage.start_run(conn, cfg["source"])
    res = RunResult(run_id=run_id)
    budget = int(cfg["max_requests_per_day"]) - storage.requests_today(conn)
    page_size = min(int(cfg["page_size"]), 50)
    seen: set[str] = set()
    order: list[tuple[str, str]] = []   # (posting_id, source_job_id) 목록에서 만난 순서
    refetch: set[str] = set()           # 목록 내용이 바뀌어 본문도 다시 받을 공고
    incomplete, errors = False, []

    try:
        for kw in cfg["keywords"]:
            page = 1
            while True:
                if budget <= 0:
                    incomplete = True
                    errors.append("하루 호출 상한 도달")
                    break
                try:
                    data = client.search(kw, page=page, page_size=page_size)
                except rocketpunch.AuthError:
                    raise
                except rocketpunch.ApiError as e:
                    incomplete = True
                    errors.append(f"{kw}: {e}")
                    log.warning("키워드 '%s' (page %d) 실패: %s", kw, page, e)
                    break
                res.requests += 1
                budget -= 1
                items = data["items"]
                res.fetched += len(items)
                for item in items:
                    row = rocketpunch.normalize(item)
                    if row is None or row["posting_id"] in seen:
                        continue
                    seen.add(row["posting_id"])
                    order.append((row["posting_id"], row["source_job_id"]))
                    is_new, changed = storage.upsert_posting(conn, run_id, item, row)
                    res.new += is_new
                    res.updated += changed
                    if changed:
                        refetch.add(row["posting_id"])
                conn.commit()
                total_pages = int(data.get("totalPages") or 0)
                if not items or page >= total_pages:
                    break
                page += 1
            if budget <= 0:
                break

        # 본문(상세) 받기: 아직 못 받았거나 목록 내용이 바뀐 공고만
        todo = [(pid, jid) for pid, jid in order if pid in refetch or not storage.has_detail(conn, pid)]
        fails = 0
        for i, (pid, jid) in enumerate(todo):
            if budget <= 0:
                incomplete = True
                errors.append(f"하루 호출 상한으로 본문 {len(todo) - i}건 남음(다음 실행에서 이어서 받음)")
                break
            try:
                raw = client.detail(jid)
            except rocketpunch.AuthError:
                raise
            except rocketpunch.NotFound:
                res.requests += 1
                budget -= 1
                log.info("본문 없음(삭제/임시저장): %s", pid)
                continue
            except rocketpunch.ApiError as e:
                res.requests += 1
                budget -= 1
                incomplete = True
                fails += 1
                if len(errors) < 5:
                    errors.append(f"본문 {pid}: {e}")
                log.warning("본문 %s 실패: %s", pid, e)
                if fails >= MAX_CONSECUTIVE_DETAIL_FAILS:
                    errors.append(f"본문 요청이 연속 {fails}회 실패해 중단(남은 {len(todo) - i - 1}건은 다음 실행에서)")
                    break
                continue
            fails = 0
            res.requests += 1
            budget -= 1
            storage.upsert_detail(conn, run_id, "rocketpunch", jid, raw, rocketpunch.normalize_detail(raw))
            conn.commit()
            res.details += 1

        res.status = "partial" if incomplete else "success"
        res.error = "; ".join(errors)
    except rocketpunch.AuthError as e:
        res.status, res.auth_failed, res.error = "failed", True, str(e)
    storage.finish_run(conn, run_id, res.status, res.requests, res.fetched, res.new, res.updated, res.error)
    return res


def anomalies(conn, res: RunResult) -> list[str]:
    """조용한 실패를 막기 위한 경고 목록"""
    warns = []
    if res.status == "failed":
        warns.append(f"수집 실패: {res.error}")
    elif res.status == "partial":
        warns.append(f"일부만 수집됨: {res.error}")
    if res.status == "success" and res.fetched == 0:
        warns.append("수집 건수가 0건입니다 (API 변경/키 문제 가능성)")
    prev = storage.previous_fetched(conn, res.run_id)
    if res.status == "success" and prev and res.fetched < prev * 0.5:
        warns.append(f"수집 건수가 직전({prev}건) 대비 절반 미만으로 줄었습니다 ({res.fetched}건)")
    return warns


def main(argv=None) -> int:
    load_dotenv(ROOT / ".env")
    p = argparse.ArgumentParser()
    p.add_argument("--config")
    p.add_argument("--db")
    p.add_argument("--no-backup", action="store_true")
    args = p.parse_args(argv)

    (ROOT / "data" / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(ROOT / "data" / "logs" / "collect.log", encoding="utf-8")])
    key = os.getenv("ROCKETPUNCH_APP_KEY", "").strip()
    if not key.startswith("rp_app_"):
        log.error("ROCKETPUNCH_APP_KEY 가 없거나 rp_app_ 로 시작하지 않습니다. .env 를 확인하세요.")
        return 2
    cfg = load_config(args.config)
    client = rocketpunch.Client(key, delay=float(cfg["request_delay_sec"]), retries=int(cfg["retries"]))

    conn = storage.connect(args.db)
    res = collect(conn, client, cfg)
    log.info("결과: %s | 호출 %d, 수신 %d, 신규 %d, 변경 %d, 본문 %d건 받음",
             res.status, res.requests, res.fetched, res.new, res.updated, res.details)
    for w in anomalies(conn, res):
        log.warning("⚠ %s", w)
    if not args.no_backup:
        log.info("백업: %s", storage.backup(conn, int(cfg["backup_keep"])))
    if res.auth_failed:
        return 2
    return 1 if res.status == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())