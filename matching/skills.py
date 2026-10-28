"""6-2: 내 기술과 공고 기술의 맞춤 점수.

    python -m matching.skills

입력: profile.yaml 의 skills (to_learn 은 쓰지 않음), data/agent.db, preferences.yaml
출력: data/ranked_skills.csv  (신입 접근 가능 공고 = 통과 + 후보만, 맞춤 점수순)

맞춤 점수 = 기존 점수(matching/score.py) + 내 기술과 일치한 기술 수(최대 4)
  - 기술은 analysis/report.py 의 TECH 사전에 있는 것만 센다 (언급 여부이며 필수 요구와 다르다)
  - 통과(신입 근거 있음)가 먼저, 후보(주니어 포함, 신입 근거 없음)는 그 뒤. 같은 구분 안에서 맞춤 점수순
  - 부족 기술은 점수에서 깎지 않고 표시만 한다 (배울 것을 정하는 용도)
"""
import csv
from collections import Counter
from pathlib import Path

import yaml

from analysis.report import TECH, TECH_RX
from collector import storage
from matching import extras, score

ROOT = storage.ROOT
MAX_BONUS = 4
SQL_FAMILY = {"MySQL", "PostgreSQL"}  # 이 DB 를 쓸 수 있으면 SQL 도 쓸 수 있다고 본다

QUERY = """
SELECT p.posting_id,
       COALESCE(p.title,'') AS title, COALESCE(d.duty,'') AS duty,
       COALESCE(d.minimum_qualification,'') AS minimum_qualification,
       COALESCE(d.description,'') AS description, COALESCE(d.preferred_qualification,'') AS preferred,
       COALESCE(d.benefit,'') AS benefit, COALESCE(d.hire_notes,'') AS hire_notes
FROM postings p LEFT JOIN posting_details d ON d.posting_id = p.posting_id
WHERE p.last_run_id = (SELECT MAX(last_run_id) FROM postings)
"""


def load_profile(path: Path | None = None) -> dict:
    p = path or ROOT / "profile.yaml"
    if not p.exists():
        raise SystemExit(f"{p} 가 없습니다. profile.example.yaml 을 복사해서 만들고 skills 를 채우세요.")
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def flatten_skills(profile: dict) -> list[str]:
    s = profile.get("skills") or []
    if isinstance(s, dict):
        s = [x for v in s.values() for x in (v or [])]
    return [str(x) for x in s]


def my_tech(skills: list[str]) -> set[str]:
    """내 기술 중 TECH 사전에 있는 것의 이름 집합."""
    mine = set()
    low = {s.lower().strip() for s in skills}
    for name, words in TECH.items():
        if name.lower() in low or any(w.lower() in low for w in words):
            mine.add(name)
    if mine & SQL_FAMILY:
        mine.add("SQL")
    return mine


def posting_techs(row) -> tuple[set[str], set[str]]:
    """(본문에서 언급된 기술, 우대 사항에서만 언급된 기술)"""
    main = f"{row['title']} {row['duty']} {row['minimum_qualification']} {row['description']}".lower()
    pref = (row["preferred"] or "").lower()
    in_main = {k for k, rx in TECH_RX.items() if rx.search(main)}
    in_pref = {k for k, rx in TECH_RX.items() if rx.search(pref)}
    return in_main | in_pref, in_pref - in_main


def build(conn, prefs: dict, mine: set[str]) -> list[dict]:
    texts = {r["posting_id"]: r for r in conn.execute(QUERY)}
    out = []
    for r in score.build(conn, prefs):
        if r["tier"] not in ("통과", "후보(주니어 포함)"):
            continue
        mentioned, pref_only = posting_techs(texts[r["posting_id"]])
        have = sorted(mentioned & mine)
        missing = sorted(mentioned - mine - pref_only)
        pref_missing = sorted(pref_only - mine)
        bonus = min(len(have), MAX_BONUS)
        out.append({**r, **extras.extract(texts[r["posting_id"]]), "mentioned": len(mentioned), "have": have, "missing": missing, "pref_missing": pref_missing,
                    "bonus": bonus, "fit_score": r["score"] + bonus,
                    "match_rate": (len(have) / len(mentioned)) if mentioned else 0.0})
    tier_order = {"통과": 0, "후보(주니어 포함)": 1}
    out.sort(key=lambda r: r["first_seen"] or "", reverse=True)
    out.sort(key=lambda r: (tier_order[r["tier"]], -r["fit_score"], -r["match_rate"]))
    return out


HEADER = ["맞춤 순위", "구분", "맞춤 점수", "기존 점수", "기술 보너스", "회사", "제목", "규모", "직무군", "언급 기술 수", "내 기술 일치",
          "부족 기술(본문)", "부족 기술(우대만)", "경력 구분", "급여(본문 문구)", "근무지(본문 문구)", "링크", "공고 ID"]


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for i, r in enumerate(rows, 1):
            w.writerow([i, r["tier"], r["fit_score"], r["score"], r["bonus"], r["company"], r["title"], r["size"], r["job_group"],
                        r["mentioned"], ", ".join(r["have"]), ", ".join(r["missing"]), ", ".join(r["pref_missing"]),
                        r["seniorities"], r["pay"], r["place"], r["url"], r["posting_id"]])


def missing_summary(rows: list[dict], top: int = 8) -> list[tuple[str, int]]:
    c = Counter()
    for r in rows:
        c.update(r["missing"])
    return c.most_common(top)


def main():
    prefs = score.load_prefs()
    profile = load_profile()
    skills = flatten_skills(profile)
    mine = my_tech(skills)
    conn = storage.connect()
    rows = build(conn, prefs, mine)
    out = ROOT / "data" / "ranked_skills.csv"
    write_csv(rows, out)
    print(f"내 기술 {len(skills)}개 중 공고 분석에 쓰인 기술 {len(mine)}개: {', '.join(sorted(mine)) or '(없음)'}")
    print(f"신입 접근 가능 {len(rows)}건 (통과 {sum(r['tier'] == '통과' for r in rows)} + 후보 {sum(r['tier'] != '통과' for r in rows)})")
    no_tech = sum(1 for r in rows if r["mentioned"] == 0)
    print(f"기술 언급이 하나도 없는 공고 {no_tech}건 (보너스 0)")
    print("\n[맞춤 순위 상위 15건]")
    for i, r in enumerate(rows[:15], 1):
        print(f"  {i:2d}. {r['fit_score']}점(기존 {r['score']}+기술 {r['bonus']}) | {(r['title'] or '')[:26]} | {(r['company'] or '')[:12]} | {r['size']} | 일치 {len(r['have'])}/{r['mentioned']}")
    print("\n[신입 접근 가능 공고에서 내가 부족한 기술 (본문에 언급, 건수)]")
    for k, v in missing_summary(rows):
        print(f"  {k}: {v}건")
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()