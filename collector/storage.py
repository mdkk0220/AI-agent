"""SQLite 저장소.

원칙: 원본(raw_postings)은 보존하고, postings 는 거기서 다시 만들 수 있는 정리본이다.
원본은 내용이 바뀐 경우에만 새 행을 추가한다 (매일 같은 공고를 중복 저장하지 않음).
"""
import hashlib
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCHEMA = """
CREATE TABLE IF NOT EXISTS fetch_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT, started_at TEXT, finished_at TEXT,
    status TEXT,                       -- running / success / partial / failed
    requests INTEGER DEFAULT 0, fetched_count INTEGER DEFAULT 0,
    new_count INTEGER DEFAULT 0, updated_count INTEGER DEFAULT 0, error TEXT
);
CREATE TABLE IF NOT EXISTS raw_postings (
    source TEXT, source_job_id TEXT, payload_hash TEXT,
    run_id INTEGER, fetched_at TEXT, payload_json TEXT,
    PRIMARY KEY (source, source_job_id, payload_hash)
);
CREATE TABLE IF NOT EXISTS postings (
    posting_id TEXT PRIMARY KEY, source TEXT, source_job_id TEXT,
    title TEXT, subtitle TEXT, job_category TEXT, seniorities TEXT,
    employment_types TEXT, work_type TEXT,
    company_id TEXT, company_name TEXT, company_industry TEXT, company_size TEXT,
    end_at TEXT, web_url TEXT, has_body INTEGER DEFAULT 0,
    first_seen TEXT, last_seen TEXT, last_run_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_postings_last_seen ON postings(last_seen);
CREATE TABLE IF NOT EXISTS raw_details (
    source TEXT, source_job_id TEXT, payload_hash TEXT,
    run_id INTEGER, fetched_at TEXT, payload_json TEXT,
    PRIMARY KEY (source, source_job_id, payload_hash)
);
CREATE TABLE IF NOT EXISTS posting_details (
    posting_id TEXT PRIMARY KEY,
    status TEXT, hiring INTEGER,
    description TEXT, duty TEXT, minimum_qualification TEXT, preferred_qualification TEXT,
    benefit TEXT, hire_process TEXT, hire_notes TEXT, apply_type TEXT, apply_url TEXT,
    detail_fetched_at TEXT, detail_run_id INTEGER
);
"""

POSTING_COLS = [
    "posting_id", "source", "source_job_id", "title", "subtitle", "job_category", "seniorities",
    "employment_types", "work_type", "company_id", "company_name", "company_industry", "company_size",
    "end_at", "web_url", "has_body",
]


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def db_path(path: str | None = None) -> str:
    return path or os.getenv("AGENT_DB") or str(ROOT / "data" / "agent.db")


def connect(path: str | None = None) -> sqlite3.Connection:
    p = db_path(path)
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def payload_hash(item: dict) -> str:
    return hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def start_run(conn, source: str) -> int:
    cur = conn.execute("INSERT INTO fetch_runs(source, started_at, status) VALUES (?,?,?)", (source, now_str(), "running"))
    conn.commit()
    return cur.lastrowid


def finish_run(conn, run_id: int, status: str, requests: int, fetched: int, new: int, updated: int, error: str = ""):
    conn.execute(
        "UPDATE fetch_runs SET finished_at=?, status=?, requests=?, fetched_count=?, new_count=?, updated_count=?, error=? "
        "WHERE run_id=?", (now_str(), status, requests, fetched, new, updated, error[:500], run_id))
    conn.commit()


def upsert_posting(conn, run_id: int, raw_item: dict, row: dict) -> tuple[bool, bool]:
    """(새 공고인가, 내용이 바뀌었나)"""
    ts = now_str()
    existed = conn.execute("SELECT 1 FROM postings WHERE posting_id=?", (row["posting_id"],)).fetchone() is not None
    cur = conn.execute(
        "INSERT OR IGNORE INTO raw_postings(source, source_job_id, payload_hash, run_id, fetched_at, payload_json) "
        "VALUES (?,?,?,?,?,?)",
        (row["source"], row["source_job_id"], payload_hash(raw_item), run_id, ts, json.dumps(raw_item, ensure_ascii=False)))
    changed = cur.rowcount == 1 and existed
    cols = ", ".join(POSTING_COLS)
    ph = ", ".join("?" for _ in POSTING_COLS)
    updates = ", ".join(f"{c}=excluded.{c}" for c in POSTING_COLS if c not in ("posting_id", "has_body"))
    conn.execute(
        f"INSERT INTO postings({cols}, first_seen, last_seen, last_run_id) VALUES ({ph}, ?, ?, ?) "
        f"ON CONFLICT(posting_id) DO UPDATE SET {updates}, last_seen=excluded.last_seen, last_run_id=excluded.last_run_id",
        [row[c] for c in POSTING_COLS] + [ts, ts, run_id])
    return (not existed), changed


DETAIL_COLS = ["status", "hiring", "description", "duty", "minimum_qualification", "preferred_qualification",
               "benefit", "hire_process", "hire_notes", "apply_type", "apply_url"]


def has_detail(conn, posting_id: str) -> bool:
    return conn.execute("SELECT 1 FROM posting_details WHERE posting_id=?", (posting_id,)).fetchone() is not None


def upsert_detail(conn, run_id: int, source: str, source_job_id: str, raw: dict, row: dict) -> None:
    """상세 원본은 내용이 바뀐 경우에만 새 행으로 보존하고, posting_details 는 최신본으로 덮어쓴다."""
    ts = now_str()
    posting_id = f"{source}:{source_job_id}"
    conn.execute(
        "INSERT OR IGNORE INTO raw_details(source, source_job_id, payload_hash, run_id, fetched_at, payload_json) "
        "VALUES (?,?,?,?,?,?)",
        (source, source_job_id, payload_hash(raw), run_id, ts, json.dumps(raw, ensure_ascii=False)))
    cols = ", ".join(DETAIL_COLS)
    ph = ", ".join("?" for _ in DETAIL_COLS)
    updates = ", ".join(f"{c}=excluded.{c}" for c in DETAIL_COLS)
    conn.execute(
        f"INSERT INTO posting_details(posting_id, {cols}, detail_fetched_at, detail_run_id) VALUES (?, {ph}, ?, ?) "
        f"ON CONFLICT(posting_id) DO UPDATE SET {updates}, detail_fetched_at=excluded.detail_fetched_at, "
        f"detail_run_id=excluded.detail_run_id",
        [posting_id] + [row[c] for c in DETAIL_COLS] + [ts, run_id])
    conn.execute("UPDATE postings SET has_body=1 WHERE posting_id=?", (posting_id,))


def requests_today(conn) -> int:
    """오늘(로컬 기준) 이미 쓴 호출 수 (하루 상한 계산용)"""
    start = datetime.now().strftime("%Y-%m-%d 00:00:00")
    return int(conn.execute("SELECT COALESCE(SUM(requests),0) FROM fetch_runs WHERE started_at >= ?", (start,)).fetchone()[0])


def previous_fetched(conn, before_run_id: int) -> int | None:
    """직전 성공 실행의 수신 건수 (급감 감지용)"""
    r = conn.execute("SELECT fetched_count FROM fetch_runs WHERE status='success' AND run_id < ? ORDER BY run_id DESC LIMIT 1",
                     (before_run_id,)).fetchone()
    return None if not r else int(r[0])


def backup(conn, keep: int = 14, dest_dir: Path | None = None) -> Path:
    dest_dir = dest_dir or (ROOT / "data" / "backups")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"agent-{datetime.now():%Y%m%d}.db"
    out = sqlite3.connect(dest)
    try:
        conn.backup(out)
    finally:
        out.close()
    for old in sorted(dest_dir.glob("agent-*.db"))[:-keep]:
        old.unlink()
    return dest