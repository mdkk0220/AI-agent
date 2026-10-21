"""수집된 공고 현황 요약 (분류 체계를 정하기 위한 재료 확인용)

    python -m collector.summary
"""
from collections import Counter

from . import storage


def top(conn, col, n=15, split=False):
    c = Counter()
    for (v,) in conn.execute(f"SELECT {col} FROM postings"):
        for x in (v.split(",") if split else [v]):
            c[x.strip() or "(비어 있음)"] += 1
    print(f"\n[{col}]")
    for k, v in c.most_common(n):
        print(f"  {v:4d}  {k}")


def main():
    conn = storage.connect()
    total = conn.execute("SELECT COUNT(*) FROM postings").fetchone()[0]
    print(f"공고 총 {total}건")
    top(conn, "job_category")
    top(conn, "company_industry")
    top(conn, "seniorities", split=True)
    top(conn, "employment_types", split=True)
    top(conn, "work_type")
    top(conn, "company_size")
    print("\n[제목 샘플 40건]")
    for t, c in conn.execute("SELECT title, company_name FROM postings ORDER BY RANDOM() LIMIT 40"):
        print(f"  - {t}  ({c})")


if __name__ == "__main__":
    main()