"""급여·지역 문구가 본문에서 어떻게 적혀 있는지 짧게 본다 (키워드 앞뒤 30자). 공고 15건씩 무작위.
실행: python scripts\\sample_snippets.py
"""
import random
import re
import sqlite3
import sys
from pathlib import Path

db = Path(__file__).resolve().parent.parent / "data" / "agent.db"
if not db.exists():
    sys.exit(f"DB가 없습니다: {db}")
c = sqlite3.connect(db)
c.row_factory = sqlite3.Row
rows = c.execute("select posting_id, benefit, description, hire_notes, minimum_qualification, duty from posting_details").fetchall()

PAY = re.compile(r"연봉|급여|월급|만\s?원|연\s?\d{3,}")
LOC = re.compile(r"근무\s?지|근무\s?장소|서울|판교|경기|강남|부산|대구|인천|대전|광주|수원|성남")


def snippets(r, rx):
    out = []
    for col in ("benefit", "description", "hire_notes", "minimum_qualification", "duty"):
        text = " ".join((r[col] or "").split())
        for m in rx.finditer(text):
            out.append(f"[{col}] ..." + text[max(0, m.start() - 30): m.end() + 30] + "...")
            break
    return out


random.seed(1)
for name, rx in (("급여", PAY), ("지역", LOC)):
    hits = [r for r in rows if snippets(r, rx)]
    print(f"\n===== {name}: {len(hits)}/{len(rows)}건에서 발견. 무작위 15건 =====")
    for r in random.sample(hits, min(15, len(hits))):
        print("-", r["posting_id"].split(":")[-1], snippets(r, rx)[0])