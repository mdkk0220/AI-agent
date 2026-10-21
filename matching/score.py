"""조건 필터 + 적합도 점수 (규칙 기반).

    python -m matching.score

입력: data/agent.db (공고 + 본문), preferences.yaml (내 조건)
출력: data/ranked.csv (통과한 공고가 점수순으로 먼저, 그다음 후보, 제외된 공고는 이유와 함께 뒤에)

판단 순서
 1) IT 직무인가      : 제목 키워드 → 직군 분류 순서로 판단
 2) 진짜 신입 가능인가 : 제목의 연차 → 자격 요건 → 주요 업무 → 상세 내용의 문구 → 없으면 로켓펀치 BEGINNER 표시
 3) 후보            : IT 인데 신입 근거가 없고 경력 구분에 JUNIOR 가 있으면 '후보(주니어 포함)' 로 주 순위 뒤에 따로 표시
 4) 점수            : 관심 직무 +3, 중견 이상 +2, 정규직/인턴 +1 (동점이면 직무가 더 분명한 공고, 그다음 최근 공고)

규칙 기반이라 틀릴 수 있다. 정확도는 사용자가 직접 표시한 지원 의향과 비교해서 잰다.
"""
import csv
import re
from pathlib import Path

import yaml

from collector import storage

ROOT = storage.ROOT
W_JOB, W_SIZE, W_EMP = 3, 2, 1  # 점수 가중치

IT_CATEGORIES = ("dev", "dataAi", "engineer")


def _rx(words):
    """한글은 부분 일치, 영문은 단어 경계로 일치하는 정규식 (ai 가 email 에 걸리지 않도록)."""
    parts = []
    for w in words:
        w = w.lower()
        parts.append(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])" if re.fullmatch(r"[a-z0-9 .\-+#]+", w) else re.escape(w))
    return re.compile("|".join(parts))


# ---------- 1) IT 직무 판정 ----------
TITLE_POS = _rx(["개발", "엔지니어", "engineer", "developer", "프로그래머", "programmer", "백엔드", "backend", "프론트", "frontend",
                 "풀스택", "fullstack", "full stack", "데이터 분석", "데이터분석", "data analyst", "data scientist", "data engineer",
                 "데이터 엔지니어", "데이터 아키텍트", "data architect", "데이터 모델러", "머신러닝", "ml", "llm", "딥러닝",
                 "qa", "devops", "sre", "dba", "보안", "임베디드", "펌웨어", "firmware"])
TITLE_NEG = _rx(["마케터", "마케팅", "영업", "세일즈", "sales", "디자이너", "designer", "경영지원", "인사", "hr", "재무", "회계",
                 "콘텐츠", "크리에이터", "퍼실리테이터", "교육", "운영 매니저", "cs", "고객 상담", "pm", "product manager",
                 "기획", "사업개발", "bd", "컨설턴트"])


# '엔지니어' 가 붙어도 개발 직무가 아닌 제목 (세일즈 엔지니어, PO 등) — 개발 키워드보다 먼저 검사한다
TITLE_NOT_IT = _rx(["세일즈 엔지니어", "sales engineer", "pre-sales", "presales", "프리세일즈", "기술영업", "po", "product owner"])

NOT_DEV = re.compile(r"사업\s*개발|business development")  # '사업개발' 의 '개발' 이 IT 키워드로 잡히지 않게 제거


def classify_it(row) -> tuple[bool, str]:
    title = (row["title"] or "").lower()
    if TITLE_NOT_IT.search(title):
        return False, "제외: 제목에 영업/기획 키워드"
    if TITLE_POS.search(NOT_DEV.sub(" ", title)):
        return True, "제목 키워드"
    if TITLE_NEG.search(title):
        return False, "제외: 제목에 비IT 키워드"
    if row["job_category"] in IT_CATEGORIES:
        return True, "직군 분류"
    return False, "제외: IT 신호 없음"


# ---------- 직무군 ----------
GROUPS = {
    "웹 개발": ["백엔드", "backend", "back-end", "프론트", "frontend", "front-end", "풀스택", "fullstack", "full stack",
               "웹 개발", "웹개발", "spring", "react", "next.js", "vue", "node.js", "django", "api"],
    "모바일 앱": ["안드로이드", "android", "ios", "모바일", "flutter", "react native", "kotlin", "swift", "앱 개발", "앱개발"],
    "데이터": ["데이터", "data", "분석가", "analyst", "bi", "sql", "etl", "빅데이터"],
    "AI·LLM 개발": ["ai", "llm", "에이전트", "agent", "머신러닝", "machine learning", "딥러닝", "nlp", "자연어",
                  "컴퓨터 비전", "computer vision", "생성형"],
    "기타IT": ["임베디드", "embedded", "펌웨어", "firmware", "반도체", "회로", "hw", "보안", "security", "인프라", "infra",
             "devops", "sre", "qa", "테스트", "네트워크", "network", "블록체인", "blockchain", "게임", "game", "unity", "c++",
             "위성", "gnss"],
}
GROUP_RX = {g: _rx(ws) for g, ws in GROUPS.items()}


def _hits(rx, text: str) -> int:
    return len(set(rx.findall(text)))


def job_group_fit(row) -> tuple[str, int]:
    """(직무군, 일치 강도). 제목에서 일치한 서로 다른 키워드 1개당 3점(최대 3개), 주요 업무는 1개당 1점(최대 2개).
    가장 높은 직무군을 고르고, 동점이면 위쪽 직무군. 아무 신호도 없으면 기타IT."""
    title = (row["title"] or "").lower()
    duty = (row["duty"] or "").lower()
    best, best_score = "기타IT", 0
    for g, rx in GROUP_RX.items():
        sc = 3 * min(_hits(rx, title), 3) + min(_hits(rx, duty), 2)
        if sc > best_score:
            best, best_score = g, sc
    return best, best_score


def job_group(row) -> str:
    return job_group_fit(row)[0]


# ---------- 2) 진짜 신입 가능 판정 ----------
NEWBIE_NO = re.compile(r"신입\s*(?:은\s*)?(?:제외|불가|지원\s*불가)")
NEWBIE_OK = re.compile(r"신입|경력\s*무관|경력무관|경력\s*불문|졸업\s*예정|채용\s*전환|채용전환")
CAREER = [
    re.compile(r"경력\s*(?:[가-힣]{0,6}\s*)?(\d+)\s*년\s*(?:이상|↑|\+)"),          # 경력 3년 이상
    re.compile(r"(\d+)\s*년\s*(?:이상|↑|\+)\s*(?:의\s*)?(?:[가-힣]{0,6}\s*)?경력"),     # 3년 이상의 (실무) 경력
    re.compile(r"경력\s*(\d+)\s*[~\-–]\s*\d+\s*년"),                                 # 경력 3~5년
]
CAREER_JOB = re.compile(r"경력직")
OTHERS_NEWBIE = re.compile(r"신입\s*사원(?!\s*(?:을|를|모집|채용|공채))")  # '신입사원이/들에게 …' 처럼 다른 사람을 가리키는 표현은 채용 근거가 아님 ('신입사원을 모집' 은 근거)
TITLE_YEARS = [
    re.compile(r"(\d+)\s*[~\-–]\s*\d+\s*년"),                 # (3~10년)
    re.compile(r"(\d+)\s*년\s*(?:이상|↑|\+)"),                   # 3년 이상
    re.compile(r"경력\s*(\d+)\s*년"),                           # 경력 3년
]


def _find_career(text: str):
    """'경력 N년 이상' 류 문구 중 최소 연차(1 이상)와 그 일치 위치. 바로 뒤에 '우대'가 붙으면 필수가 아니므로 무시."""
    found = []
    for rx in CAREER:
        for m in rx.finditer(text):
            if "우대" in text[m.end(): m.end() + 8]:
                continue
            n = int(m.group(1))
            if n >= 1:
                found.append((n, m))
    return min(found, key=lambda x: x[0]) if found else None


def career_years(text: str) -> int | None:
    r = _find_career(text)
    return r[0] if r else None


def _snip(text: str, m) -> str:
    """일치한 문구 앞뒤 15자를 한 줄로 (ranked.csv 에서 판정 근거를 눈으로 확인하기 위함)"""
    return " ".join(text[max(0, m.start() - 15): m.end() + 15].split())


def classify_beginner(row) -> tuple[str, str, str]:
    """(신입가능 / 신입불가, 근거 위치, 근거 문구)"""
    title = row["title"] or ""
    if "신입" not in title:  # 제목에 연차(3~10년, 경력 5년 이상 등)가 있으면 본문보다 우선해서 신입불가
        for rx in TITLE_YEARS:
            m = rx.search(title)
            if m and int(m.group(1)) >= 1:
                return "신입불가", "제목 문구", _snip(title, m)
    fields = [("자격 요건", row["minimum_qualification"]), ("주요 업무", row["duty"]), ("상세 내용", row["description"])]
    for name, text in fields:
        text = OTHERS_NEWBIE.sub(" ", text or "")
        if not text.strip():
            continue
        m = NEWBIE_NO.search(text)
        if m:
            return "신입불가", f"{name} 문구", _snip(text, m)
        m = NEWBIE_OK.search(text)
        if m:
            return "신입가능", f"{name} 문구", _snip(text, m)
        c = _find_career(text)
        if c:
            return "신입불가", f"{name} 문구", _snip(text, c[1])
        m = CAREER_JOB.search(text)
        if m:
            return "신입불가", f"{name} 문구", _snip(text, m)
    seniorities = (row["seniorities"] or "").split(",")
    employment = (row["employment_types"] or "").split(",")
    if "BEGINNER" in seniorities or "INTERN" in employment:
        return "신입가능", "문구 없음 → BEGINNER/인턴 표시", ""
    return "신입불가", "문구 없음 → BEGINNER 표시 없음", ""


# ---------- 3) 점수 ----------
def load_prefs(path: Path | None = None) -> dict:
    with open(path or ROOT / "preferences.yaml", encoding="utf-8") as f:
        p = yaml.safe_load(f) or {}
    p.setdefault("must", {})
    p.setdefault("prefer", {})
    return p


def score_row(row, group: str, prefs: dict) -> tuple[int, str]:
    pref = prefs["prefer"]
    score, why = 0, []
    if group in (pref.get("job_groups") or []):
        score += W_JOB
        why.append(f"직무 {group} +{W_JOB}")
    if (row["company_size"] or "") in (pref.get("company_size") or []):
        score += W_SIZE
        why.append(f"규모 {row['company_size']} +{W_SIZE}")
    emp = set((row["employment_types"] or "").split(","))
    if emp & set(pref.get("employment") or []):
        score += W_EMP
        why.append(f"고용 +{W_EMP}")
    return score, ", ".join(why)


QUERY = """
SELECT p.posting_id, p.title, p.company_name, p.company_size, p.company_industry, p.job_category,
       p.seniorities, p.employment_types, p.work_type, p.web_url, p.first_seen,
       COALESCE(d.duty,'') AS duty, COALESCE(d.minimum_qualification,'') AS minimum_qualification,
       COALESCE(d.description,'') AS description
FROM postings p LEFT JOIN posting_details d ON d.posting_id = p.posting_id
WHERE p.last_run_id = (SELECT MAX(last_run_id) FROM postings)
"""


def build(conn, prefs: dict) -> list[dict]:
    must = prefs["must"]
    out = []
    for row in conn.execute(QUERY):
        is_it, it_why = classify_it(row)
        group, fit = job_group_fit(row) if is_it else ("", 0)
        newbie, newbie_why, newbie_evidence = classify_beginner(row)
        reasons = []
        if must.get("it_job", True) and not is_it:
            reasons.append(it_why)
        if must.get("beginner", True) and newbie != "신입가능":
            reasons.append(f"제외: {newbie} ({newbie_why})")
        # 후보: IT 인데 신입 근거가 없고(문구 없음 + 신입 표시 없음) 경력 구분에 JUNIOR 가 포함된 공고 → 주 순위 밖에 따로 표시
        candidate = (is_it and newbie_why == "문구 없음 → BEGINNER 표시 없음"
                     and "JUNIOR" in (row["seniorities"] or "").split(","))
        if candidate:
            reasons = ["후보: JUNIOR 포함, 신입 근거 없음 (신입 지원 가능한지 직접 확인)"]
        score, why = score_row(row, group, prefs) if (not reasons or candidate) else (0, "")
        out.append({
            "tier": "통과" if not reasons else ("후보(주니어 포함)" if candidate else "제외"),
            "passed": not reasons, "score": score, "excluded_reason": " / ".join(reasons),
            "title": row["title"], "company": row["company_name"], "size": row["company_size"],
            "job_group": group, "fit": fit, "it_basis": it_why, "newbie": newbie, "newbie_basis": newbie_why,
            "newbie_evidence": newbie_evidence,
            "seniorities": row["seniorities"], "employment": row["employment_types"], "work_type": row["work_type"], "score_detail": why,
            "duty": " ".join((row["duty"] or "").split())[:150], "url": row["web_url"],
            "first_seen": row["first_seen"], "posting_id": row["posting_id"],
        })
    # 통과 → 후보 → 제외 순 → 점수 높은 순 → 같으면 직무가 더 분명한 공고 → 그래도 같으면 최근 공고 (안정 정렬 두 번)
    out.sort(key=lambda r: r["first_seen"] or "", reverse=True)
    tier_order = {"통과": 0, "후보(주니어 포함)": 1, "제외": 2}
    out.sort(key=lambda r: (tier_order[r["tier"]], -r["score"], -r["fit"]))
    return out


COLUMNS = [("rank", "순위"), ("score", "점수"), ("passed", "통과"), ("tier", "구분"), ("excluded_reason", "제외 사유"), ("title", "제목"),
           ("company", "회사"), ("size", "규모"), ("job_group", "직무군"), ("newbie", "신입 판정"), ("newbie_basis", "신입 근거"),
           ("newbie_evidence", "신입 근거 문구"), ("seniorities", "경력 구분"), ("it_basis", "IT 근거"), ("employment", "고용 형태"), ("work_type", "근무 형태"), ("score_detail", "점수 내역"),
           ("duty", "주요 업무(앞부분)"), ("url", "링크"), ("first_seen", "처음 본 날"), ("posting_id", "공고 ID")]


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([label for _, label in COLUMNS])
        for r in rows:
            w.writerow([("O" if r[k] else "X") if k == "passed" else r.get(k, "") for k, _ in COLUMNS])


def main():
    prefs = load_prefs()
    conn = storage.connect()
    rows = build(conn, prefs)
    rank = 0
    for r in rows:
        if r["passed"]:
            rank += 1
            r["rank"] = rank
        else:
            r["rank"] = ""
    out = ROOT / "data" / "ranked.csv"
    write_csv(rows, out)

    n_it = sum(1 for r in rows if r["it_basis"] and not r["it_basis"].startswith("제외"))
    by_text = sum(1 for r in rows if r["newbie_basis"].endswith("문구"))
    print(f"현재 모집 중 공고 {len(rows)}건 → IT 직무 {n_it}건 → (IT 이면서) 신입 가능 통과 {rank}건")
    print(f"신입 판정 근거: 본문 문구 {by_text}건 / 문구 없음 → 표시 따름 {len(rows) - by_text}건")
    cands = [r for r in rows if r["tier"] == "후보(주니어 포함)"]
    print(f"\n주 순위 {rank}건 + 후보(주니어 포함, 신입 근거 없음) {len(cands)}건 → 직접 볼 대상 {rank + len(cands)}건")
    print("\n[상위 15건]")
    for r in rows[:15]:
        if r["passed"]:
            print(f"  {r['rank']:2d}. {r['score']}점 | {r['title'][:32]} | {r['company'][:14]} | {r['size']} | {r['job_group']}")
    if cands:
        print("\n[후보(주니어 포함) 상위 10건]")
        for r in cands[:10]:
            print(f"  {r['score']}점 | {r['title'][:32]} | {r['company'][:14]} | {r['size']} | {r['seniorities']}")
    print(f"\n전체 순위표 저장: {out}")


if __name__ == "__main__":
    main()