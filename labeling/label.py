"""정답 세트 라벨링 도구.

    python -m labeling.label --test          # 연습 (data/labels_test.csv, 정답 세트에 안 들어감)
    python -m labeling.label                 # 본 라벨링 (data/labels.csv, 기본 목표 100건)
    python -m labeling.label --recheck       # 이미 라벨링한 10건을 다시 보고 일관성 측정

일부러 로켓펀치의 job_category / seniorities 는 보여주지 않는다 (라벨이 그쪽으로 쏠리는 것을 막기 위해).
입력할 때마다 바로 저장되므로 중간에 꺼도 이어서 할 수 있다.
"""
import argparse
import csv
import random
from datetime import datetime
from pathlib import Path

from collector import storage

DATA = storage.ROOT / "data"

GROUPS = ["백엔드", "프론트엔드", "풀스택", "모바일", "AI·ML", "데이터", "임베디드·HW",
          "보안", "인프라·QA", "네트워크", "기획·PM", "기타IT"]
FIELDS = ["posting_id", "is_it", "job_group", "labeled_at"]


def read_labels(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_all(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def append_label(path: Path, row: dict):
    if not path.exists():
        write_all(path, [row])
        return
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        csv.DictWriter(f, fieldnames=FIELDS).writerow(row)


def make_row(posting_id: str, is_it: str, group: str) -> dict:
    return {"posting_id": posting_id, "is_it": is_it, "job_group": group,
            "labeled_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


def ask_label(post: dict, ask=input, out=print):
    """한 건 라벨링. 반환: ('label', is_it, group) / ('skip',) / ('undo',) / ('quit',)"""
    out(f"\n제목: {post['title']}")
    if post["subtitle"]:
        out(f"부제: {post['subtitle']}")
    out(f"회사: {post['company_name']}")
    while True:
        a = ask("IT 직무? y/n  (s=건너뛰기 u=이전 취소 q=종료) > ").strip().lower()
        if a in ("s", "u", "q"):
            return {"s": ("skip",), "u": ("undo",), "q": ("quit",)}[a]
        if a == "n":
            return ("label", "비IT", "")
        if a == "y":
            break
        out("y / n / s / u / q 중에서 입력하세요.")
    out("  " + "  ".join(f"{i}.{g}" for i, g in enumerate(GROUPS, 1)))
    while True:
        a = ask("직무군 번호 (b=뒤로) > ").strip().lower()
        if a == "b":
            return ask_label(post, ask, out)
        if a.isdigit() and 1 <= int(a) <= len(GROUPS):
            return ("label", "IT", GROUPS[int(a) - 1])
        out(f"1~{len(GROUPS)} 사이 숫자를 입력하세요.")


def load_postings(conn, ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    ph = ",".join("?" for _ in ids)
    rows = conn.execute(f"SELECT posting_id, title, subtitle, company_name FROM postings WHERE posting_id IN ({ph})", ids)
    return {r["posting_id"]: dict(r) for r in rows}


def run_labeling(conn, path: Path, n: int, seed: int, ask=input, out=print) -> int:
    """path 에 n 건이 될 때까지 라벨링. 반환: 이번에 새로 라벨링한 건수"""
    done = {r["posting_id"] for r in read_labels(path)}
    pool = [r[0] for r in conn.execute("SELECT posting_id FROM postings ORDER BY posting_id") if r[0] not in done]
    random.Random(seed).shuffle(pool)
    posts = load_postings(conn, pool)
    queue, session, new = list(pool), [], 0
    while queue and len(done) < n:
        out(f"\n--- 진행 {len(done)}/{n} ---")
        pid = queue.pop(0)
        res = ask_label(posts[pid], ask, out)
        if res[0] == "quit":
            break
        if res[0] == "skip":
            continue
        if res[0] == "undo":
            queue.insert(0, pid)
            if not session:
                out("취소할 입력이 없습니다.")
                continue
            last = session.pop()
            write_all(path, [r for r in read_labels(path) if r["posting_id"] != last])
            done.discard(last)
            queue.insert(0, last)
            new -= 1
            out("직전 라벨을 취소했습니다.")
            continue
        append_label(path, make_row(pid, res[1], res[2]))
        done.add(pid)
        session.append(pid)
        new += 1
    out(f"\n저장됨: {path}  (현재 {len(done)}건, 이번에 {new}건)")
    return new


def run_recheck(conn, main_path: Path, re_path: Path, n: int, seed: int, ask=input, out=print):
    """이미 라벨링한 공고를 다시 보고, 처음 답과 얼마나 같은지 계산"""
    first = {r["posting_id"]: r for r in read_labels(main_path)}
    done = {r["posting_id"] for r in read_labels(re_path)}
    ids = sorted(i for i in first if i not in done)
    random.Random(seed).shuffle(ids)
    posts = load_postings(conn, ids[:n])
    for pid in ids[:n]:
        out(f"\n--- 다시 보기 {len(done) + 1}/{n} ---")
        res = ask_label(posts[pid], ask, out)
        if res[0] == "quit":
            break
        if res[0] in ("skip", "undo"):
            continue
        append_label(re_path, make_row(pid, res[1], res[2]))
        done.add(pid)
    again = {r["posting_id"]: r for r in read_labels(re_path)}
    same_it = sum(first[i]["is_it"] == r["is_it"] for i, r in again.items())
    both_it = [i for i, r in again.items() if r["is_it"] == "IT" and first[i]["is_it"] == "IT"]
    same_grp = sum(first[i]["job_group"] == again[i]["job_group"] for i in both_it)
    out(f"\n일관성: IT 여부 {same_it}/{len(again)} 일치"
        + (f", 직무군 {same_grp}/{len(both_it)} 일치" if both_it else ""))
    return len(again), same_it, len(both_it), same_grp


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--test", action="store_true", help="연습 모드")
    p.add_argument("--recheck", action="store_true", help="일관성 확인 모드")
    p.add_argument("--n", type=int, help="목표 건수 (본: 100, 연습/다시보기: 10)")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args(argv)
    conn = storage.connect()
    if args.recheck:
        run_recheck(conn, DATA / "labels.csv", DATA / "labels_recheck.csv", args.n or 10, args.seed)
    elif args.test:
        run_labeling(conn, DATA / "labels_test.csv", args.n or 10, args.seed + 1)
    else:
        run_labeling(conn, DATA / "labels.csv", args.n or 100, args.seed)


if __name__ == "__main__":
    main()