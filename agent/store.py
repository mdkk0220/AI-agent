"""지원 현황과 승인된 초안을 파일로 저장한다. 어디에도 제출하지 않는다.

data/tracker.json   지원 현황 (관심 → 지원 준비 → 서류 제출 → 면접 → 결과)
data/drafts/*.md    사람이 승인한 자소서 초안
"""
import json
import re
from datetime import datetime
from pathlib import Path

from collector import storage

STAGES = ["관심", "지원 준비", "서류 제출", "면접", "결과"]


def data_dir() -> Path:
    return Path(storage.db_path()).parent


def tracker_path() -> Path:
    return data_dir() / "tracker.json"


def drafts_dir() -> Path:
    return data_dir() / "drafts"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def load_tracker() -> list[dict]:
    p = tracker_path()
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def _save(items: list[dict]) -> None:
    p = tracker_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def add(posting: dict, stage: str = "관심") -> bool:
    """이미 있으면 추가하지 않고 False."""
    items = load_tracker()
    if any(i["posting_id"] == posting["posting_id"] for i in items):
        return False
    items.append({"posting_id": posting["posting_id"], "company": posting.get("company") or "", "title": posting.get("title") or "",
                  "size": posting.get("size") or "", "score": posting.get("fit_score"), "url": posting.get("url") or "",
                  "stage": stage, "note": "", "added_at": _now(), "updated_at": _now()})
    _save(items)
    return True


def set_stage(posting_id: str, stage: str, note: str | None = None) -> None:
    if stage not in STAGES:
        raise ValueError(f"알 수 없는 단계: {stage}")
    items = load_tracker()
    for i in items:
        if i["posting_id"] == posting_id:
            i["stage"], i["updated_at"] = stage, _now()
            if note is not None:
                i["note"] = note
    _save(items)


def move(posting_id: str, step: int) -> None:
    items = load_tracker()
    for i in items:
        if i["posting_id"] == posting_id:
            idx = max(0, min(len(STAGES) - 1, STAGES.index(i["stage"]) + step))
            i["stage"], i["updated_at"] = STAGES[idx], _now()
    _save(items)


def remove(posting_id: str) -> None:
    _save([i for i in load_tracker() if i["posting_id"] != posting_id])


def save_draft(posting: dict, sentences: list[dict], summary: dict) -> Path:
    """승인된 초안을 마크다운 파일로 저장 (제거된 문장은 넣지 않고, TODO 는 그대로 둔다)."""
    d = drafts_dir()
    d.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", str(posting["posting_id"]))
    path = d / f"{safe}.md"
    head = [f"# {posting.get('title') or ''}", "",
            f"- 회사: {posting.get('company') or ''}", f"- 공고: {posting.get('url') or ''}",
            f"- 승인: {_now()} (사람이 승인함, 제출은 하지 않음)",
            f"- 팩트체크: 문장 {summary['total']}개 중 근거 있음 {summary['ok']}, TODO {summary['todo']}, 제거 {summary['remove']}"]
    body = [s["text"] for s in sentences if s["status"] != "remove"]
    path.write_text("\n".join(head) + "\n\n## 초안\n\n" + "\n\n".join(body) + "\n", encoding="utf-8")
    return path
