"""급여·지역·규모 정보가 어디에 있는지 확인한다 (개수와 키 이름만 출력, 회사 내용은 출력하지 않음).
실행: python scripts\\check_fields.py
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
db = ROOT / "data" / "agent.db"
if not db.exists():
    sys.exit(f"DB가 없습니다: {db}")
c = sqlite3.connect(db)

row = c.execute("select payload_json from raw_details limit 1").fetchone()
if row:
    d = json.loads(row[0])
    co = d.get("company")
    print("1. company 안의 키:", sorted(co.keys()) if isinstance(co, dict) else f"(객체 아님: {type(co).__name__})")

n = c.execute("select count(*) from posting_details").fetchone()[0]
print("2. 본문 있는 공고:", n)

def count(words, cols):
    cond = " or ".join(f"{col} like ?" for col in cols for _ in words)
    args = [f"%{w}%" for _ in cols for w in words]
    return c.execute(f"select count(*) from posting_details where {cond}", args).fetchone()[0]

cols = ["benefit", "description", "hire_notes", "minimum_qualification", "duty"]
print("   연봉·급여 문구 포함:", count(["연봉", "급여", "만원", "월급"], cols))
print("   지명 포함:", count(["서울", "판교", "경기", "강남", "부산", "대구", "인천", "대전", "광주", "수원", "성남", "근무지", "근무 장소", "근무장소"], cols))