"""내 조건(업종·직무·규모·근무 형태)을 정하기 위한 현황 요약.

    python -m collector.overview

- 신입 가능 공고(seniorities 에 BEGINNER 포함)만 따로 집계한다.
- 전체 공고를 data/postings_view.csv 로 저장한다 (엑셀로 열어서 훑어보기용).
"""
import csv
from collections import Counter

from . import storage

IT_LIKE = ("dev", "dataAi", "engineer", "rnd")  # 로켓펀치 직무 중 IT 에 가까운 것 (거친 기준, 정확도 평가 대상 아님)


def is_beginner(row) -> bool:
    return "BEGINNER" in (row["seniorities"] or "").split(",")


def show(title, values, n=12):
    c = Counter((v or "(비어 있음)") for v in values)
    print(f"\n[{title}]")
    for k, v in c.most_common(n):
        print(f"  {v:4d}  {k}")


def main():
    conn = storage.connect()
    rows = conn.execute("SELECT * FROM postings ORDER BY first_seen DESC").fetchall()
    beg = [r for r in rows if is_beginner(r)]
    print(f"전체 {len(rows)}건 / 신입 가능 {len(beg)}건")

    show("신입 가능 - 직무(로켓펀치 분류)", [r["job_category"] for r in beg])
    show("신입 가능 - 업종", [r["company_industry"] for r in beg])
    show("신입 가능 - 회사 규모", [r["company_size"] for r in beg])
    show("신입 가능 - 근무 형태", [r["work_type"] for r in beg])
    show("신입 가능 - 고용 형태", [t for r in beg for t in (r["employment_types"] or "").split(",")])

    it_beg = [r for r in beg if r["job_category"] in IT_LIKE]
    print(f"\n[신입 가능 + IT 계열 공고 {len(it_beg)}건 (최대 60건 표시)]")
    for r in it_beg[:60]:
        print(f"  - {r['title']} | {r['company_name']} | {r['company_industry']} | {r['company_size']} | {r['work_type']}")

    out = storage.ROOT / "data" / "postings_view.csv"
    cols = ["title", "company_name", "job_category", "company_industry", "company_size",
            "seniorities", "employment_types", "work_type", "end_at", "web_url", "first_seen"]
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([r[c] for c in cols])
    print(f"\n전체 공고 표 저장: {out}")


if __name__ == "__main__":
    main()