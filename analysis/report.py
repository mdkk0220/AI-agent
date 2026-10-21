"""5단계: 수집한 공고 현황 분석.

    python -m analysis.report

입력: data/agent.db (공고 + 본문), preferences.yaml
출력: data/analysis/ 아래 CSV 4개 + data/analysis/analysis.md (요약)
  by_group.csv    직무군별 공고 수 / 신입 접근 가능(통과+후보) / 중견 이상
  by_size.csv     회사 규모별 공고 수
  by_industry.csv 업종별 공고 수 (IT 직무 기준, 상위)
  tech.csv        기술 키워드가 언급된 공고 수 (IT 전체 vs 신입 접근 가능)

'IT' 와 '신입 통과/후보' 판정은 matching/score.py 의 결과를 그대로 쓴다.
기술 키워드는 제목 + 주요 업무 + 자격 요건 + 우대 사항 + 상세 내용에서 단어 단위로 찾는다 (언급 = 요구가 아니라 등장 여부).
"""
import csv
from collections import Counter
from pathlib import Path

from collector import storage
from matching import score

ROOT = storage.ROOT
OUT = ROOT / "data" / "analysis"

TECH = {
    "Python": ["python", "파이썬"], "Java": ["java", "자바"], "Kotlin": ["kotlin", "코틀린"], "Swift": ["swift", "스위프트"],
    "TypeScript": ["typescript"], "JavaScript": ["javascript"], "React": ["react", "리액트"], "Next.js": ["next.js", "nextjs"],
    "Vue": ["vue", "vue.js"], "Node.js": ["node.js", "nodejs", "nest.js", "nestjs"], "Spring": ["spring", "스프링"],
    "Django/FastAPI/Flask": ["django", "fastapi", "flask"], "C++": ["c++"], "C#": ["c#"], "Unity": ["unity", "유니티"],
    "Go": ["golang"], "Flutter": ["flutter"],
    "SQL": ["sql"], "MySQL": ["mysql"], "PostgreSQL": ["postgresql", "postgres"], "MongoDB": ["mongodb"], "Redis": ["redis"],
    "AWS": ["aws"], "GCP": ["gcp", "google cloud"], "Azure": ["azure"], "Docker": ["docker", "도커"],
    "Kubernetes": ["kubernetes", "k8s"], "Git": ["git", "github"],
    "LLM": ["llm"], "RAG": ["rag"], "LangChain/LangGraph": ["langchain", "langgraph"], "PyTorch": ["pytorch"],
    "TensorFlow": ["tensorflow"], "Pandas": ["pandas"], "Tableau/BI": ["tableau", "power bi", "looker"],
    "Spark/Airflow": ["spark", "airflow"], "머신러닝/딥러닝": ["머신러닝", "machine learning", "딥러닝", "deep learning"],
}
TECH_RX = {k: score._rx(v) for k, v in TECH.items()}

TEXT_QUERY = """
SELECT p.posting_id, p.title, p.company_industry, p.company_size,
       COALESCE(d.duty,'') || ' ' || COALESCE(d.minimum_qualification,'') || ' ' ||
       COALESCE(d.preferred_qualification,'') || ' ' || COALESCE(d.description,'') AS body
FROM postings p LEFT JOIN posting_details d ON d.posting_id = p.posting_id
WHERE p.last_run_id = (SELECT MAX(last_run_id) FROM postings)
"""
BIG = ("MEDIUM", "LARGE", "HUGE")


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def table(header: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def analyze(conn, prefs: dict) -> dict:
    ranked = score.build(conn, prefs)
    texts = {r["posting_id"]: r for r in conn.execute(TEXT_QUERY)}

    it_rows = [r for r in ranked if r["it_basis"] and not r["it_basis"].startswith("제외")]
    open_rows = [r for r in it_rows if r["tier"] in ("통과", "후보(주니어 포함)")]  # 신입 접근 가능

    # 직무군
    groups = {}
    for r in it_rows:
        g = groups.setdefault(r["job_group"], {"all": 0, "pass": 0, "cand": 0, "big_all": 0, "big_open": 0})
        g["all"] += 1
        g["pass"] += r["tier"] == "통과"
        g["cand"] += r["tier"] == "후보(주니어 포함)"
        big = r["size"] in BIG
        g["big_all"] += big
        g["big_open"] += big and r["tier"] in ("통과", "후보(주니어 포함)")
    group_rows = sorted(([k, v["all"], v["pass"], v["cand"], v["big_all"], v["big_open"]] for k, v in groups.items()),
                        key=lambda x: -(x[2] + x[3]))

    # 규모
    size_order = ["TINY", "SMALL", "MEDIUM", "LARGE", "HUGE", ""]
    size_all = Counter(r["size"] or "" for r in ranked)
    size_it = Counter(r["size"] or "" for r in it_rows)
    size_open = Counter(r["size"] or "" for r in open_rows)
    size_rows = [[s or "(없음)", size_all[s], size_it[s], size_open[s]] for s in size_order if size_all[s]]

    # 업종 (IT 직무)
    ind_it = Counter()
    ind_open = Counter()
    for r in it_rows:
        ind = texts[r["posting_id"]]["company_industry"] or "(없음)"
        ind_it[ind] += 1
        ind_open[ind] += r["tier"] in ("통과", "후보(주니어 포함)")
    industry_rows = [[k, v, ind_open[k]] for k, v in ind_it.most_common(15)]

    # 기술
    tech_all, tech_open = Counter(), Counter()
    tech_by_group = {}
    for r in it_rows:
        t = texts[r["posting_id"]]
        body = f"{t['title']} {t['body']}".lower()
        is_open = r["tier"] in ("통과", "후보(주니어 포함)")
        for k, rx in TECH_RX.items():
            if rx.search(body):
                tech_all[k] += 1
                tech_open[k] += is_open
                tech_by_group.setdefault(r["job_group"], Counter())[k] += 1
    n_it, n_open = len(it_rows), len(open_rows)
    tech_rows = [[k, tech_all[k], f"{tech_all[k] / n_it * 100:.0f}%", tech_open[k],
                  f"{tech_open[k] / n_open * 100:.0f}%" if n_open else "-"]
                 for k in sorted(TECH, key=lambda x: (-tech_all[x], x)) if tech_all[k]]

    return {"total": len(ranked), "it": n_it, "open": n_open,
            "passed": sum(r["tier"] == "통과" for r in it_rows), "cand": sum(r["tier"] == "후보(주니어 포함)" for r in it_rows),
            "group_rows": group_rows, "size_rows": size_rows, "industry_rows": industry_rows, "tech_rows": tech_rows,
            "tech_by_group": tech_by_group}


def render_md(a: dict) -> str:
    out = ["# 공고 현황 분석 (로켓펀치 기준)", "",
           f"- 모집 중 공고 {a['total']}건 → IT 직무 {a['it']}건 → 신입 접근 가능 {a['open']}건 (통과 {a['passed']} + 후보 {a['cand']})",
           "- 한계: 로켓펀치 한 곳의 수집 시점 스냅샷이다. 소기업 비중이 크다. 기술 키워드는 '언급 여부'이며 필수 요구와 다르다.",
           "", "## 직무군별 (IT 직무 기준)", "",
           table(["직무군", "IT 공고", "신입 통과", "후보", "중견 이상 전체", "중견 이상 중 신입 접근 가능"], a["group_rows"]), "",
           "## 회사 규모별", "", table(["규모", "전체", "IT 직무", "IT 중 신입 접근 가능"], a["size_rows"]), "",
           "## 업종별 상위 15 (IT 직무)", "", table(["업종", "IT 공고", "신입 접근 가능"], a["industry_rows"]), "",
           "## 기술 키워드 언급", "", table(["기술", "IT 전체", "비율", "신입 접근 가능", "비율"], a["tech_rows"]), "",
           "## 직무군별 많이 언급된 기술 (상위 6)", ""]
    for g, c in sorted(a["tech_by_group"].items()):
        out.append(f"- {g}: " + ", ".join(f"{k} {v}" for k, v in c.most_common(6)))
    return "\n".join(out) + "\n"


def main():
    prefs = score.load_prefs()
    conn = storage.connect()
    a = analyze(conn, prefs)
    write_csv(OUT / "by_group.csv", ["직무군", "IT 공고", "신입 통과", "후보", "중견 이상 전체", "중견 이상 중 신입 접근 가능"], a["group_rows"])
    write_csv(OUT / "by_size.csv", ["규모", "전체", "IT 직무", "IT 중 신입 접근 가능"], a["size_rows"])
    write_csv(OUT / "by_industry.csv", ["업종", "IT 공고", "신입 접근 가능"], a["industry_rows"])
    write_csv(OUT / "tech.csv", ["기술", "IT 전체", "비율", "신입 접근 가능", "비율"], a["tech_rows"])
    md = render_md(a)
    (OUT / "analysis.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"저장: {OUT}")


if __name__ == "__main__":
    main()