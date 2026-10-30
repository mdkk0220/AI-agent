"""규칙 분류기 평가: 내가 만든 정답 세트(data/labels.csv)와 matching/score.py 의 규칙 판정을 비교한다.

    python -m classifier.evaluate

출력: 화면 요약 + data/analysis/eval_errors.csv (틀린 공고 목록, 규칙을 고칠 때 참고)
측정하는 것
  1) IT / 비IT 판정: 정확도, 정밀도(IT 라고 한 것 중 진짜 IT), 재현율(진짜 IT 중 잡아낸 것)
  2) 직무군 판정: 정답이 IT 이고 규칙도 IT 라고 한 공고만 대상. 규칙의 직무군은 5개라서 정답 12개 값을 묶어서 비교한다.
주의: 정답 세트가 작으면(예: 100건, 그중 IT 약 30건) 숫자는 대략적인 값이다. 건수를 항상 같이 적는다.
"""
import csv
from pathlib import Path

from collector import storage
from labeling.label import read_labels
from matching import score

# 정답의 직무군 12개 → 규칙의 직무군 5개
GROUP_MAP = {
    "백엔드": "웹 개발", "프론트엔드": "웹 개발", "풀스택": "웹 개발",
    "모바일": "모바일 앱", "데이터": "데이터", "AI·ML": "AI·LLM 개발",
}
OTHER = "기타IT"


def to_rule_group(gold_group: str) -> str:
    return GROUP_MAP.get(gold_group, OTHER)


def it_metrics(pairs: list[tuple[bool, bool]]) -> dict:
    """pairs: (정답이 IT, 규칙이 IT) 목록"""
    tp = sum(g and p for g, p in pairs)
    fp = sum((not g) and p for g, p in pairs)
    fn = sum(g and (not p) for g, p in pairs)
    tn = sum((not g) and (not p) for g, p in pairs)
    n = len(pairs)
    return {
        "n": n, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "accuracy": (tp + tn) / n if n else None,
        "precision": tp / (tp + fp) if (tp + fp) else None,
        "recall": tp / (tp + fn) if (tp + fn) else None,
    }


def group_metrics(pairs: list[tuple[str, str]]) -> dict:
    """pairs: (정답 직무군 12개 중 하나, 규칙 직무군)"""
    n = len(pairs)
    ok = sum(to_rule_group(g) == p for g, p in pairs)
    return {"n": n, "correct": ok, "accuracy": ok / n if n else None}


QUERY = """
SELECT p.posting_id, p.title, p.company_name, p.job_category,
       COALESCE(d.duty,'') AS duty
FROM postings p LEFT JOIN posting_details d ON d.posting_id = p.posting_id
WHERE p.posting_id IN ({ph})
"""


def evaluate(conn, labels: list[dict]) -> dict:
    ids = [r["posting_id"] for r in labels]
    rows = {r["posting_id"]: r for r in conn.execute(QUERY.format(ph=",".join("?" for _ in ids)), ids)} if ids else {}
    it_pairs, grp_pairs, errors = [], [], []
    for lab in labels:
        row = rows.get(lab["posting_id"])
        if row is None:
            continue  # DB 에 없는 공고는 평가에서 뺀다
        gold_it = lab["is_it"] == "IT"
        pred_it, why = score.classify_it(row)
        it_pairs.append((gold_it, pred_it))
        if gold_it != pred_it:
            errors.append({"종류": "IT판정", "제목": row["title"], "회사": row["company_name"], "정답": lab["is_it"],
                           "규칙": "IT" if pred_it else "비IT", "규칙 근거": why, "posting_id": lab["posting_id"]})
        elif gold_it and pred_it:
            pred_group, _ = score.job_group_fit(row)
            grp_pairs.append((lab["job_group"], pred_group))
            if to_rule_group(lab["job_group"]) != pred_group:
                errors.append({"종류": "직무군", "제목": row["title"], "회사": row["company_name"],
                               "정답": f"{lab['job_group']} (→ {to_rule_group(lab['job_group'])})", "규칙": pred_group,
                               "규칙 근거": "", "posting_id": lab["posting_id"]})
    return {"it": it_metrics(it_pairs), "group": group_metrics(grp_pairs), "errors": errors}


def _pct(x):
    return "-" if x is None else f"{x * 100:.1f}%"


def main():
    path = storage.ROOT / "data" / "labels.csv"
    labels = read_labels(path)
    if not labels:
        print(f"정답 세트가 없습니다: {path}\n먼저 python -m labeling.label 로 라벨링하세요.")
        return
    res = evaluate(storage.connect(), labels)
    m, g = res["it"], res["group"]
    print(f"정답 세트 {len(labels)}건 중 평가 대상 {m['n']}건")
    print("\n[IT / 비IT 판정]")
    print(f"  정확도 {_pct(m['accuracy'])}  (맞힌 {m['tp'] + m['tn']} / {m['n']})")
    print(f"  정밀도 {_pct(m['precision'])}  (규칙이 IT 라고 한 {m['tp'] + m['fp']}건 중 진짜 IT {m['tp']}건)")
    print(f"  재현율 {_pct(m['recall'])}  (진짜 IT {m['tp'] + m['fn']}건 중 규칙이 잡은 것 {m['tp']}건)")
    print(f"  오탐(비IT 를 IT 로) {m['fp']}건 · 누락(IT 를 비IT 로) {m['fn']}건")
    print("\n[직무군 판정] (정답도 IT 이고 규칙도 IT 라고 한 공고만, 정답 12개 값을 규칙의 5개로 묶어 비교)")
    print(f"  정확도 {_pct(g['accuracy'])}  ({g['correct']} / {g['n']}건)")
    if g["n"] < 30:
        print("  ※ 건수가 30건 미만이라 대략적인 값입니다. 포트폴리오에는 건수를 같이 적으세요.")
    out = storage.ROOT / "data" / "analysis" / "eval_errors.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    cols = ["종류", "제목", "회사", "정답", "규칙", "규칙 근거", "posting_id"]
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(res["errors"])
    print(f"\n틀린 공고 {len(res['errors'])}건 → {out}")


if __name__ == "__main__":
    main()
