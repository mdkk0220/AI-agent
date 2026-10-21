"""4단계: 지원 의향 O/X 표시 도구 + 일치율 리포트.

실행 (프로젝트 루트에서):
    python -m labeling.mark            # 표시 시작 (이어하기 가능)
    python -m labeling.mark --report   # 결과 집계
    python -m labeling.mark --reset    # 처음부터 다시 (표시 기록 삭제)

입력: data/ranked.csv (python -m matching.score 로 만든 파일)
출력: data/interest_sample.csv (뽑은 30건, 고정), data/interest.csv (내 표시)
점수·통과 여부·순위는 표시하는 동안 보이지 않는다.
"""
import csv
import random
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RANKED = ROOT / "data" / "ranked.csv"
SAMPLE = ROOT / "data" / "interest_sample.csv"
ANSWERS = ROOT / "data" / "interest.csv"

N_TOP, N_LOW, N_EXCL = 10, 10, 10
SEED = 42
GROUP_LABEL = {"top": "통과 상위", "low": "통과 중하위", "excl": "IT인데 제외"}


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def make_sample() -> list[dict]:
    rows = read_csv(RANKED)
    rng = random.Random(SEED)
    passed = sorted((r for r in rows if r["통과"] == "O"), key=lambda r: int(r["순위"]))
    top = passed[:N_TOP]
    rest = passed[N_TOP:]
    low = rng.sample(rest, min(N_LOW, len(rest)))
    # IT 직무인데 신입 조건 때문에 제외된 공고 (IT 아님으로 제외된 것은 뺀다)
    excl_pool = [r for r in rows if r["통과"] == "X"
                 and "IT 신호 없음" not in r["제외 사유"] and "비IT" not in r["제외 사유"]]
    excl = rng.sample(excl_pool, min(N_EXCL, len(excl_pool)))
    sample = []
    for group, items in (("top", top), ("low", low), ("excl", excl)):
        for r in items:
            sample.append({"posting_id": r["공고 ID"], "group": group, "rank": r["순위"], "score": r["점수"]})
    rng.shuffle(sample)
    return sample


def load_sample() -> list[dict]:
    if SAMPLE.exists():
        return read_csv(SAMPLE)
    sample = make_sample()
    write_csv(SAMPLE, sample, ["posting_id", "group", "rank", "score"])
    return sample


def load_answers() -> list[dict]:
    return read_csv(ANSWERS) if ANSWERS.exists() else []


def save_answers(rows: list[dict]) -> None:
    write_csv(ANSWERS, rows, ["posting_id", "group", "answer", "marked_at"])


def show(post: dict, idx: int, total: int) -> None:
    print("\n" + "=" * 70)
    print(f"[{idx}/{total}] {post['회사']} | {post['제목']}")
    print(f"규모 {post['규모']} · 고용 {post['고용 형태']} · 근무 {post['근무 형태']}")
    duty = (post["주요 업무(앞부분)"] or "").replace("\n", " ")
    print(f"주요 업무: {duty[:300]}")
    print(f"링크: {post['링크']}")
    print("-" * 70)


def mark() -> None:
    if not RANKED.exists():
        sys.exit("data/ranked.csv 가 없습니다. 먼저 python -m matching.score 를 실행하세요.")
    sample = load_sample()
    by_id = {r["공고 ID"]: r for r in read_csv(RANKED)}
    answers = load_answers()
    done = {a["posting_id"] for a in answers}
    todo = [s for s in sample if s["posting_id"] not in done]
    print(f"총 {len(sample)}건 중 {len(done)}건 표시함, 남은 {len(todo)}건")
    print("o = 지원하고 싶다 / x = 관심 없다 / s = 모르겠다·건너뜀 / u = 방금 것 취소 / q = 저장하고 종료")
    i = len(done)
    for s in todo:
        post = by_id.get(s["posting_id"])
        if post is None:
            continue
        i += 1
        show(post, i, len(sample))
        while True:
            key = input("o / x / s / u / q > ").strip().lower()
            if key in ("o", "x", "s"):
                answers.append({"posting_id": s["posting_id"], "group": s["group"], "answer": key,
                                "marked_at": datetime.now().isoformat(timespec="seconds")})
                save_answers(answers)
                break
            if key == "u":
                if answers:
                    undone = answers.pop()
                    save_answers(answers)
                    print(f"취소함: {undone['posting_id']} (다음 실행 때 다시 나옵니다. 지금은 q 로 종료하세요)")
                else:
                    print("취소할 것이 없습니다.")
                continue
            if key == "q":
                print("저장하고 종료합니다. 다시 실행하면 이어서 합니다.")
                return
            print("o, x, s, u, q 중에서 입력하세요.")
    print("\n전부 표시했습니다. python -m labeling.mark --report 로 결과를 보세요.")


def report() -> None:
    answers = load_answers()
    if not answers:
        sys.exit("표시 기록이 없습니다. 먼저 python -m labeling.mark 로 표시하세요.")
    print(f"표시한 공고 {len(answers)}건 (s 는 비율 계산에서 제외)\n")
    stat = {}
    for a in answers:
        g = stat.setdefault(a["group"], {"o": 0, "x": 0, "s": 0})
        g[a["answer"]] += 1
    for group in ("top", "low", "excl"):
        g = stat.get(group)
        if not g:
            continue
        n = g["o"] + g["x"]
        rate = f"{g['o'] / n * 100:.0f}%" if n else "-"
        print(f"{GROUP_LABEL[group]:<10} 지원 의향 O {g['o']} / X {g['x']} / 건너뜀 {g['s']}  → O 비율 {rate}")
    top, low = stat.get("top"), stat.get("low")
    print("\n해석 기준: 상위의 O 비율이 중하위보다, 중하위가 제외보다 높을수록 시스템 순서가 내 판단과 맞는 것.")
    if top and (top["o"] + top["x"]) and low and (low["o"] + low["x"]):
        t = top["o"] / (top["o"] + top["x"])
        l = low["o"] / (low["o"] + low["x"])
        print("상위 > 중하위" if t > l else "상위 <= 중하위 (규칙 점검 필요)")
    print("\n내가 O 라고 했는데 시스템이 제외한 공고 / 시스템 상위인데 내가 X 라고 한 공고:")
    by_id = {r["공고 ID"]: r for r in read_csv(RANKED)}
    for a in answers:
        post = by_id.get(a["posting_id"])
        if not post:
            continue
        if (a["group"] == "excl" and a["answer"] == "o") or (a["group"] == "top" and a["answer"] == "x"):
            tag = "제외됐지만 O" if a["group"] == "excl" else "상위지만 X"
            print(f" - [{tag}] {post['회사']} | {post['제목']} | {post['제외 사유'] or '통과'}")


def main() -> None:
    if "--reset" in sys.argv:
        for p in (SAMPLE, ANSWERS):
            if p.exists():
                p.unlink()
        print("표시 기록과 표본을 지웠습니다.")
        return
    if "--report" in sys.argv:
        report()
    else:
        mark()


if __name__ == "__main__":
    main()