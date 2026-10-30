"""자소서 초안 작성기 (지금은 템플릿 기반, 프로필 사실과 공고 내용만 사용).

draft(posting, profile, banned) → 문장 목록 [{"text", "kind", "evidence"}]
  - posting: matching.skills.build 가 만든 공고 한 건(dict)
  - banned: 팩트체크에서 지워진 문장들 (다시 쓸 때 같은 문장을 만들지 않기 위함)
나중에 LLM 으로 바꿀 때도 이 함수의 입력과 출력 모양만 지키면 되고, 팩트체크는 그대로 쓴다.
프로필에 없는 내용은 지어내지 않고 [TODO] 문장으로 남긴다.
"""
import os

from dotenv import load_dotenv

from agent import llm_drafter
from collector import storage
from matching.skills import flatten_skills


def _group(profile: dict, key: str) -> list[str]:
    s = profile.get("skills")
    return [str(x) for x in (s.get(key) or [])] if isinstance(s, dict) else []


def _projects(profile: dict) -> list[dict]:
    return [p for p in (profile.get("projects") or []) if isinstance(p, dict) and (p.get("name") or "").strip()]


def draft(posting: dict, profile: dict, banned: list[str] | None = None) -> list[dict]:
    """환경변수 DRAFTER=llm 이면 LLM 으로 쓰고, 안 되면 템플릿으로 대신한다 (대신한 이유는 문장의 source 에 남김)."""
    load_dotenv(storage.ROOT / ".env")
    if (os.getenv("DRAFTER") or "").strip().lower() == "llm":
        try:
            return llm_drafter.draft(posting, profile, banned)
        except llm_drafter.LlmUnavailable as e:
            return [{**s, "source": f"template (LLM 실패: {e})"} for s in draft_template(posting, profile, banned)]
    return draft_template(posting, profile, banned)


def draft_template(posting: dict, profile: dict, banned: list[str] | None = None) -> list[dict]:
    banned = set(banned or [])
    title = posting.get("title") or "공고"
    out: list[dict] = [{"text": f"{title} 포지션에 지원합니다.", "kind": "intro", "evidence": "공고 제목"}]

    major, coding = (profile.get("major") or "").strip(), (profile.get("coding_experience") or "").strip()
    if major and coding:
        out.append({"text": f"저는 {major} 전공이고, 코딩 경력은 {coding}입니다.", "kind": "claim",
                    "evidence": "프로필의 전공, 코딩 경력"})
    elif major:
        out.append({"text": f"저는 {major} 전공입니다.", "kind": "claim", "evidence": "프로필의 전공"})

    have = list(posting.get("have") or [])
    if have:
        shown = ", ".join(have[:4])
        out.append({"text": f"{shown} 등을 사용해 본 경험이 있습니다.", "kind": "claim",
                    "evidence": f"프로필의 써 본 기술 ({shown}) 중 공고에 나온 것"})
    elif flatten_skills(profile):
        skills = ", ".join(flatten_skills(profile)[:4])
        out.append({"text": f"{skills} 등을 사용해 본 경험이 있습니다.", "kind": "claim", "evidence": "프로필의 써 본 기술"})

    projects = _projects(profile)
    if projects:
        for p in projects[:2]:
            summary = (p.get("summary") or "").strip()
            role = (p.get("my_role") or "").strip()
            if summary and role:
                out.append({"text": f"{p['name']} 프로젝트에서 {summary} 이 프로젝트에서 제가 맡은 역할은 {role}입니다.", "kind": "claim",
                            "evidence": f"프로필의 프로젝트 '{p['name']}'"})
            else:
                out.append({"text": f"[TODO: '{p['name']}' 프로젝트의 내용과 내 역할을 profile.yaml 에 채워 주세요]", "kind": "todo", "evidence": ""})
    else:
        out.append({"text": "[TODO: 이 공고와 관련된 프로젝트 사례를 profile.yaml 의 projects 에 추가해 주세요]", "kind": "todo", "evidence": ""})

    duty = " ".join((posting.get("duty") or "").split())
    if duty:
        out.append({"text": f"공고의 주요 업무({duty[:60].rstrip()}…)에 기여하고 싶습니다.", "kind": "motive",
                    "evidence": "공고의 주요 업무 (지원 동기이며 경험 주장 아님)"})
    return [s for s in out if s["text"] not in banned]
