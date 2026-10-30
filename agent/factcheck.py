"""팩트체크: 초안의 각 문장이 profile.yaml 의 사실로 뒷받침되는지 규칙으로 검사한다.

판정
  ok      근거 있음 (기술 언급이 없거나, 언급한 기술이 모두 내 기술에 있음)
  todo    [TODO ...] 표시가 있는 문장 (사실이 비어 있어서 사용자가 채워야 함)
  remove  프로필에 없는 기술을 '내가 써 본 것'처럼 말하는 문장, 또는 프로필에 없는 숫자(기간·수치·성과)를 말하는 문장 → 삭제

지원 동기(motive)·인사(intro) 문장은 공고의 기술을 언급해도 경험 주장이 아니므로 기술 검사를 하지 않는다.
LLM 이 초안을 쓰게 되어도 이 검사는 그대로 쓴다.
"""
import re

import yaml

from analysis.report import TECH_RX
from matching.skills import flatten_skills, my_tech


def mentioned_tech(text: str) -> set[str]:
    low = text.lower()
    return {k for k, rx in TECH_RX.items() if rx.search(low)}


NUM_RX = re.compile(r"\d[\d,.]*")


def _profile_text(profile: dict) -> str:
    return yaml.safe_dump(profile, allow_unicode=True)


def unknown_numbers(text: str, profile: dict) -> list[str]:
    """문장에 있는 숫자 중 프로필 어디에도 없는 것. LLM 이 지어낸 수치·기간을 잡는 규칙 (기술명 검사가 못 잡는 부분)."""
    known = _profile_text(profile)
    return sorted({n.rstrip(".,") for n in NUM_RX.findall(text) if n.rstrip(".,") and n.rstrip(".,") not in known})


def check_sentence(sentence: dict, profile: dict) -> dict:
    """sentence: {"text", "kind": claim|motive|intro|todo, "evidence": str}  →  status, reason 을 채워서 돌려준다."""
    out = dict(sentence)
    text = sentence["text"]
    if "[TODO" in text or sentence.get("kind") == "todo":
        out.update(status="todo", reason="프로필에 사례가 없어 쓰지 않았습니다")
        return out
    if sentence.get("kind") in ("motive", "intro"):
        out.update(status="ok", reason=sentence.get("evidence") or "공고 내용 (지원 동기이며 경험 주장 아님)")
        return out
    mine = my_tech(flatten_skills(profile))
    missing = sorted(mentioned_tech(text) - mine)
    bad_nums = unknown_numbers(text, profile)
    if missing:
        out.update(status="remove", reason=f"프로필에 {', '.join(missing)}이(가) 없습니다")
    elif bad_nums:
        out.update(status="remove", reason=f"프로필에 없는 숫자입니다: {', '.join(bad_nums)}")
    else:
        out.update(status="ok", reason=sentence.get("evidence") or "프로필의 사실")
    return out


def check_all(sentences: list[dict], profile: dict) -> list[dict]:
    return [check_sentence(s, profile) for s in sentences]


def summary(checked: list[dict]) -> dict:
    return {"total": len(checked), "ok": sum(s["status"] == "ok" for s in checked),
            "todo": sum(s["status"] == "todo" for s in checked), "remove": sum(s["status"] == "remove" for s in checked)}
