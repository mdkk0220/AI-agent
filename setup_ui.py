"""프로젝트 루트(C:\\Users\\User\\Desktop\\AI-agent)에서 한 번만 실행:  python setup_ui.py
이미 있는 파일은 덮어쓰지 않고 건너뜁니다. 실행 후 이 파일은 지워도 됩니다."""
from pathlib import Path

FILES = {}

FILES['app.py'] = r'''"""취업 에이전트 화면 (Streamlit). 프로젝트 루트에서 실행:  streamlit run app.py

  추천 공고   : matching/skills.py 의 맞춤 순위 (신입 접근 가능 공고)
  자소서 초안 : LangGraph (초안 → 팩트체크 → 사람 승인 → 파일 저장). 어디에도 제출하지 않는다.
  지원 현황   : 관심 → 지원 준비 → 서류 제출 → 면접 → 결과 (data/tracker.json)
  프로필      : profile.yaml 읽기 전용 보기
"""
import os

import pandas as pd
import streamlit as st
from langgraph.types import Command

from agent import factcheck, profile as prof, store
from agent.graph import build_graph
from collector import storage
from matching import score
from matching import skills as sk

PAGES = ["추천 공고", "자소서 초안", "지원 현황", "프로필"]
TIERS = ["전체", "통과", "후보(주니어 포함)"]

st.set_page_config(page_title="취업 에이전트", layout="wide")


# ---------- 데이터 ----------
def _mtime(path) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


@st.cache_data(show_spinner="공고를 불러오는 중...")
def load_rows(db_mtime: float, profile_mtime: float):
    profile, _ = prof.load()
    mine = sk.my_tech(sk.flatten_skills(profile))
    conn = storage.connect()
    try:
        prefs = score.load_prefs()
        ranked = score.build(conn, prefs)
        rows = sk.build(conn, prefs, mine)
    finally:
        conn.close()
    n_it = sum(1 for r in ranked if r["it_basis"] and not r["it_basis"].startswith("제외"))
    return rows, len(ranked), n_it


@st.cache_resource
def get_graph():
    return build_graph()  # MemorySaver: 브라우저 세션이 유지되는 동안 승인 대기 상태를 기억


def go_draft(posting_id: str) -> None:
    st.session_state["draft_posting"] = posting_id
    st.session_state["page"] = "자소서 초안"


def chips(items: list[str], color: str) -> str:
    return " ".join(f":{color}-badge[{x}]" for x in items) if items else "(없음)"


# ---------- 1. 추천 공고 ----------
def page_jobs(rows, total, n_it, profile_ok):
    st.title("추천 공고")
    if not profile_ok:
        st.warning("profile.yaml 이 없어서 내 기술 일치는 0으로 계산됩니다. profile.example.yaml 을 복사해서 만들어 주세요.")
    n_pass = sum(r["tier"] == "통과" for r in rows)
    c1, c2, c3 = st.columns(3)
    c1.metric("모집 중 공고", total)
    c2.metric("IT 직무", n_it)
    c3.metric("신입 접근 가능", len(rows), f"통과 {n_pass} + 후보 {len(rows) - n_pass}", delta_color="off")

    f1, f2, f3 = st.columns([2, 1, 1])
    tier = f1.radio("구분", TIERS, horizontal=True)
    group = f2.selectbox("직무군", ["전체"] + sorted({r["job_group"] for r in rows}))
    size = f3.selectbox("규모", ["전체", "TINY", "SMALL", "MEDIUM", "LARGE", "HUGE"])
    view = [r for r in rows if (tier == "전체" or r["tier"] == tier) and (group == "전체" or r["job_group"] == group)
            and (size == "전체" or r["size"] == size)]
    if not view:
        st.info("조건에 맞는 공고가 없습니다.")
        return

    left, right = st.columns([3, 2], gap="large")
    with left:
        st.caption("정렬: 맞춤 점수 (기존 점수 + 내 기술 일치). 행을 누르면 오른쪽에 자세히 나옵니다.")
        df = pd.DataFrame([{"순위": i, "구분": r["tier"], "제목": r["title"], "회사": r["company"], "규모": r["size"],
                            "맞춤 점수": r["fit_score"], "기존": r["score"], "기술": r["bonus"],
                            "일치": f"{len(r['have'])}/{r['mentioned']}"} for i, r in enumerate(view, 1)])
        event = st.dataframe(df, hide_index=True, on_select="rerun", selection_mode="single-row", width="stretch", height=560)
        picked = event.selection.rows[0] if event.selection.rows else 0
    p = view[picked]
    with right:
        st.subheader(p["title"])
        st.write(f"{p['company']} · {p['size']} · 경력 구분 {p['seniorities']}")
        if p["tier"] == "통과":
            st.markdown(f"**신입 판정 근거**  \n{p['newbie_basis']}" + (f": \"{p['newbie_evidence']}\"" if p["newbie_evidence"] else ""))
        else:
            st.markdown("**신입 판정 근거**  \n신입 근거가 없습니다. 경력 구분에 JUNIOR가 있어 후보로만 표시했으니 공고 본문을 직접 확인하세요.")
        st.markdown(f"**점수 내역 ({p['fit_score']}점)**  \n{p['score_detail'] or '없음'}" + (f" · 내 기술 일치 +{p['bonus']}" if p["bonus"] else ""))
        st.markdown(f"**내 기술과 비교** (본문 기술 {p['mentioned']}개)")
        st.markdown("있음 " + chips(p["have"], "green"))
        st.markdown("부족 " + chips(p["missing"], "orange"))
        if p["pref_missing"]:
            st.markdown("우대만 " + chips(p["pref_missing"], "gray"))
        st.button("자소서 초안 만들기", type="primary", width="stretch", on_click=go_draft, args=(p["posting_id"],))
        b1, b2 = st.columns(2)
        if b1.button("관심 목록에 추가", width="stretch"):
            st.toast("관심 목록에 추가했습니다" if store.add(p) else "이미 목록에 있습니다")
        if p.get("url"):
            b2.link_button("공고 원문 열기", p["url"], width="stretch")


# ---------- 2. 자소서 초안 ----------
STATUS_LABEL = {"ok": ":green-badge[근거 있음]", "todo": ":orange-badge[TODO]", "remove": ":gray-badge[제거됨]"}


def render_sentences(sentences):
    for s in sentences:
        label = STATUS_LABEL[s["status"]]
        if s["status"] == "remove":
            st.markdown(f"~~{s['text']}~~")
        else:
            st.markdown(s["text"])
        st.caption(f"{label} {s.get('reason', '')}")


def page_draft(rows, profile, profile_ok):
    st.title("자소서 초안")
    pid = st.session_state.get("draft_posting")
    posting = next((r for r in rows if r["posting_id"] == pid), None)
    if posting is None:
        st.info("추천 공고에서 공고를 고른 뒤 '자소서 초안 만들기'를 누르세요.")
        return
    if not profile_ok:
        st.warning("profile.yaml 이 없습니다. 있어도 비어 있는 부분은 [TODO]로 남습니다.")
    st.subheader(posting["title"])
    st.caption(f"{posting['company']} · {posting['size']} · 맞춤 점수 {posting['fit_score']}점")

    graph = get_graph()
    run = st.session_state.get("run")
    if run is None or run["pid"] != pid:
        if st.button("초안 만들기", type="primary"):
            n = st.session_state.get("run_n", 0) + 1
            st.session_state["run_n"] = n
            cfg = {"configurable": {"thread_id": f"{pid}-{n}"}}
            result = graph.invoke({"posting": posting, "profile": profile}, cfg)
            st.session_state["run"] = {"pid": pid, "cfg": cfg, "sentences": result["sentences"], "rewrites": result.get("rewrites", 0),
                                       "saved": ""}
            st.rerun()
        return

    left, mid, right = st.columns([1, 2, 1], gap="large")
    with left:
        st.markdown("#### 초안이 쓸 수 있는 사실")
        st.caption("profile.yaml 에 적힌 것만 사용합니다.")
        st.write(f"**전공 · 상태** {profile.get('major') or '(비어 있음)'} · {profile.get('status') or ''}")
        st.write(f"**코딩 경력** {profile.get('coding_experience') or '(비어 있음)'}")
        st.write("**써 본 기술** " + (", ".join(sk.flatten_skills(profile)[:8]) or "(비어 있음)"))
        projects = [x for x in (profile.get("projects") or []) if isinstance(x, dict) and (x.get("name") or "").strip()]
        if projects:
            st.write("**프로젝트** " + ", ".join(x["name"] for x in projects))
        else:
            st.warning("프로젝트가 비어 있습니다. 사례가 필요한 문장은 지어내지 않고 TODO로 남깁니다.")
        duty = " ".join((posting.get("duty") or "").split())
        if duty:
            st.write("**공고의 주요 업무** " + duty[:200])

    sentences = run["sentences"]
    summary = factcheck.summary(sentences)
    with mid:
        st.markdown(f"#### 초안 (재작성 {run['rewrites']}/2회)")
        if st.toggle("직접 수정하기"):
            text = st.text_area("문단마다 빈 줄로 나눕니다", "\n\n".join(s["text"] for s in sentences if s["status"] != "remove"), height=320)
            if st.button("수정 반영하고 팩트체크"):
                edited = [{"text": t.strip(), "kind": "claim", "evidence": "직접 수정"} for t in text.split("\n\n") if t.strip()]
                run["sentences"] = factcheck.check_all(edited, profile)
                st.rerun()
        render_sentences(sentences)
    with right:
        st.markdown("#### 진행 상태")
        saved = run.get("saved")
        st.write("완료 · 공고 평가  \n완료 · 초안 작성  \n완료 · 팩트체크")
        st.write("**지금 · 사람 승인 대기**" if not saved else "완료 · 사람 승인")
        st.markdown("#### 팩트체크 결과")
        st.write(f"문장 {summary['total']}개 중 근거 있음 {summary['ok']}, TODO {summary['todo']}, 제거 {summary['remove']}")
        st.markdown("#### 승인")
        if saved:
            st.success(f"저장했습니다: {saved}")
            st.caption("제출되지 않았습니다. 지원은 직접 하세요. 지원 현황에 '지원 준비'로 추가했습니다.")
        else:
            if st.button("승인하고 파일로 저장", type="primary", width="stretch"):
                out = graph.invoke(Command(resume={"action": "approve", "sentences": sentences}), run["cfg"])
                run["saved"] = out.get("saved_path", "")
                st.rerun()
            if st.button("폐기", width="stretch"):
                graph.invoke(Command(resume={"action": "discard"}), run["cfg"])
                st.session_state.pop("run", None)
                st.rerun()
            st.caption("승인해도 어디에도 제출되지 않습니다. 파일로만 저장되고, 지원은 직접 합니다.")


# ---------- 3. 지원 현황 ----------
def _move(pid, step):
    store.move(pid, step)


def _remove(pid):
    store.remove(pid)


def page_tracker():
    st.title("지원 현황")
    st.caption("지원은 직접 하고, 한 뒤에는 여기서 단계만 바꿉니다. 에이전트는 어디에도 제출하지 않습니다.")
    items = store.load_tracker()
    cols = st.columns(len(store.STAGES))
    for col, stage in zip(cols, store.STAGES):
        mine = [i for i in items if i["stage"] == stage]
        with col:
            st.subheader(f"{stage} {len(mine)}")
            if not mine:
                st.caption("아직 없음")
            for i in mine:
                with st.container(border=True):
                    st.markdown(f"**{i['title']}**")
                    st.caption(f"{i['company']} · {i['size']}" + (f" · 맞춤 {i['score']}점" if i.get("score") is not None else ""))
                    b1, b2, b3 = st.columns(3)
                    b1.button("◀", key=f"prev-{i['posting_id']}", disabled=stage == store.STAGES[0], on_click=_move, args=(i["posting_id"], -1))
                    b2.button("▶", key=f"next-{i['posting_id']}", disabled=stage == store.STAGES[-1], on_click=_move, args=(i["posting_id"], 1))
                    b3.button("삭제", key=f"del-{i['posting_id']}", on_click=_remove, args=(i["posting_id"],))


# ---------- 4. 프로필 ----------
def page_profile(profile, profile_ok):
    st.title("프로필")
    st.caption(f"파일: {prof.path()} (git에 올라가지 않습니다). 수정은 이 파일을 직접 편집하세요.")
    if not profile_ok:
        st.warning("profile.yaml 이 없습니다. profile.example.yaml 을 복사해서 만들어 주세요.")
        return
    st.write(f"**전공 · 상태** {profile.get('major') or ''} · {profile.get('status') or ''}")
    st.write(f"**학력** {profile.get('education') or '(비어 있음)'}")
    st.write(f"**코딩 경력** {profile.get('coding_experience') or '(비어 있음)'}")
    skills = profile.get("skills")
    if isinstance(skills, dict):
        for k, v in skills.items():
            st.write(f"**{k}** " + (", ".join(map(str, v)) if v else "(비어 있음)"))
    else:
        st.write("**기술** " + ", ".join(map(str, skills or [])))
    st.write("**배우려는 것** " + (", ".join(map(str, profile.get("to_learn") or [])) or "(비어 있음)"))
    projects = [x for x in (profile.get("projects") or []) if isinstance(x, dict) and (x.get("name") or "").strip()]
    st.subheader(f"프로젝트 {len(projects)}개")
    for x in projects:
        with st.container(border=True):
            st.markdown(f"**{x['name']}** {x.get('period') or ''}")
            st.write(x.get("summary") or "")
            st.caption(f"역할: {x.get('my_role') or '(비어 있음)'} · 기술: {', '.join(x.get('stack') or [])}")
    if not projects:
        st.info("프로젝트가 비어 있습니다.")


# ---------- 실행 ----------
def main():
    profile, profile_ok = prof.load()
    rows, total, n_it = load_rows(_mtime(storage.db_path()), _mtime(prof.path()))
    st.sidebar.title("취업 에이전트")
    st.sidebar.radio("메뉴", PAGES, key="page")
    st.sidebar.caption("자동 제출은 하지 않습니다.")
    page = st.session_state["page"]
    if page == "추천 공고":
        page_jobs(rows, total, n_it, profile_ok)
    elif page == "자소서 초안":
        page_draft(rows, profile, profile_ok)
    elif page == "지원 현황":
        page_tracker()
    else:
        page_profile(profile, profile_ok)


main()
'''

FILES['agent/__init__.py'] = r''''''

FILES['agent/profile.py'] = r'''"""profile.yaml 읽기. 환경변수 AGENT_PROFILE 로 경로를 바꿀 수 있다 (테스트용)."""
import os
from pathlib import Path

import yaml

from collector import storage


def path() -> Path:
    return Path(os.getenv("AGENT_PROFILE") or storage.ROOT / "profile.yaml")


def load() -> tuple[dict, bool]:
    """(프로필, 파일이 있는지). 파일이 없으면 ({}, False)."""
    p = path()
    if not p.exists():
        return {}, False
    with open(p, encoding="utf-8") as f:
        return (yaml.safe_load(f) or {}), True
'''

FILES['agent/store.py'] = r'''"""지원 현황과 승인된 초안을 파일로 저장한다. 어디에도 제출하지 않는다.

data/tracker.json   지원 현황 (관심 → 지원 준비 → 서류 제출 → 면접 → 결과)
data/drafts/*.md    사람이 승인한 자소서 초안
"""
import json
import re
from datetime import datetime
from pathlib import Path

from collector import storage

STAGES = ["관심", "지원 준비", "서류 제출", "면접", "결과"]


def data_dir() -> Path:
    return Path(storage.db_path()).parent


def tracker_path() -> Path:
    return data_dir() / "tracker.json"


def drafts_dir() -> Path:
    return data_dir() / "drafts"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def load_tracker() -> list[dict]:
    p = tracker_path()
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def _save(items: list[dict]) -> None:
    p = tracker_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def add(posting: dict, stage: str = "관심") -> bool:
    """이미 있으면 추가하지 않고 False."""
    items = load_tracker()
    if any(i["posting_id"] == posting["posting_id"] for i in items):
        return False
    items.append({"posting_id": posting["posting_id"], "company": posting.get("company") or "", "title": posting.get("title") or "",
                  "size": posting.get("size") or "", "score": posting.get("fit_score"), "url": posting.get("url") or "",
                  "stage": stage, "note": "", "added_at": _now(), "updated_at": _now()})
    _save(items)
    return True


def set_stage(posting_id: str, stage: str, note: str | None = None) -> None:
    if stage not in STAGES:
        raise ValueError(f"알 수 없는 단계: {stage}")
    items = load_tracker()
    for i in items:
        if i["posting_id"] == posting_id:
            i["stage"], i["updated_at"] = stage, _now()
            if note is not None:
                i["note"] = note
    _save(items)


def move(posting_id: str, step: int) -> None:
    items = load_tracker()
    for i in items:
        if i["posting_id"] == posting_id:
            idx = max(0, min(len(STAGES) - 1, STAGES.index(i["stage"]) + step))
            i["stage"], i["updated_at"] = STAGES[idx], _now()
    _save(items)


def remove(posting_id: str) -> None:
    _save([i for i in load_tracker() if i["posting_id"] != posting_id])


def save_draft(posting: dict, sentences: list[dict], summary: dict) -> Path:
    """승인된 초안을 마크다운 파일로 저장 (제거된 문장은 넣지 않고, TODO 는 그대로 둔다)."""
    d = drafts_dir()
    d.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", str(posting["posting_id"]))
    path = d / f"{safe}.md"
    head = [f"# {posting.get('title') or ''}", "",
            f"- 회사: {posting.get('company') or ''}", f"- 공고: {posting.get('url') or ''}",
            f"- 승인: {_now()} (사람이 승인함, 제출은 하지 않음)",
            f"- 팩트체크: 문장 {summary['total']}개 중 근거 있음 {summary['ok']}, TODO {summary['todo']}, 제거 {summary['remove']}"]
    body = [s["text"] for s in sentences if s["status"] != "remove"]
    path.write_text("\n".join(head) + "\n\n## 초안\n\n" + "\n\n".join(body) + "\n", encoding="utf-8")
    return path
'''

FILES['agent/drafter.py'] = r'''"""자소서 초안 작성기 (지금은 템플릿 기반, 프로필 사실과 공고 내용만 사용).

draft(posting, profile, banned) → 문장 목록 [{"text", "kind", "evidence"}]
  - posting: matching.skills.build 가 만든 공고 한 건(dict)
  - banned: 팩트체크에서 지워진 문장들 (다시 쓸 때 같은 문장을 만들지 않기 위함)
나중에 LLM 으로 바꿀 때도 이 함수의 입력과 출력 모양만 지키면 되고, 팩트체크는 그대로 쓴다.
프로필에 없는 내용은 지어내지 않고 [TODO] 문장으로 남긴다.
"""
from matching.skills import flatten_skills


def _group(profile: dict, key: str) -> list[str]:
    s = profile.get("skills")
    return [str(x) for x in (s.get(key) or [])] if isinstance(s, dict) else []


def _projects(profile: dict) -> list[dict]:
    return [p for p in (profile.get("projects") or []) if isinstance(p, dict) and (p.get("name") or "").strip()]


def draft(posting: dict, profile: dict, banned: list[str] | None = None) -> list[dict]:
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
'''

FILES['agent/factcheck.py'] = r'''"""팩트체크: 초안의 각 문장이 profile.yaml 의 사실로 뒷받침되는지 규칙으로 검사한다.

판정
  ok      근거 있음 (기술 언급이 없거나, 언급한 기술이 모두 내 기술에 있음)
  todo    [TODO ...] 표시가 있는 문장 (사실이 비어 있어서 사용자가 채워야 함)
  remove  프로필에 없는 기술을 '내가 써 본 것'처럼 말하는 문장 → 삭제

지원 동기(motive)·인사(intro) 문장은 공고의 기술을 언급해도 경험 주장이 아니므로 기술 검사를 하지 않는다.
LLM 이 초안을 쓰게 되어도 이 검사는 그대로 쓴다.
"""
from analysis.report import TECH_RX
from matching.skills import flatten_skills, my_tech


def mentioned_tech(text: str) -> set[str]:
    low = text.lower()
    return {k for k, rx in TECH_RX.items() if rx.search(low)}


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
    if missing:
        out.update(status="remove", reason=f"프로필에 {', '.join(missing)}이(가) 없습니다")
    else:
        out.update(status="ok", reason=sentence.get("evidence") or "프로필의 사실")
    return out


def check_all(sentences: list[dict], profile: dict) -> list[dict]:
    return [check_sentence(s, profile) for s in sentences]


def summary(checked: list[dict]) -> dict:
    return {"total": len(checked), "ok": sum(s["status"] == "ok" for s in checked),
            "todo": sum(s["status"] == "todo" for s in checked), "remove": sum(s["status"] == "remove" for s in checked)}
'''

FILES['agent/graph.py'] = r'''"""LangGraph 에이전트: 공고 평가 → 초안 → 팩트체크 → (필요하면 재작성, 최대 2회) → 사람 승인(interrupt) → 저장.

    graph = build_graph()
    cfg = {"configurable": {"thread_id": posting_id}}
    graph.invoke({"posting": ..., "profile": ...}, cfg)            # 승인 대기에서 멈춘다 (state["__interrupt__"])
    graph.invoke(Command(resume={"action": "approve"}), cfg)       # 사람이 승인하면 저장 (approve / discard)

사람이 승인하기 전에는 아무것도 저장하지 않고, 승인해도 제출하지 않는다 (파일로만 저장).
"""
from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from agent import drafter, factcheck, store

MAX_REWRITES = 2


class State(TypedDict, total=False):
    posting: dict
    profile: dict
    sentences: list      # 팩트체크가 끝난 문장들 (status: ok / todo / remove)
    banned: list         # 지워진 문장 (재작성 때 다시 만들지 않기)
    rewrites: int
    summary: dict
    decision: str        # approve / discard
    saved_path: str


def evaluate(state: State) -> dict:
    p = state["posting"]
    return {"rewrites": 0, "banned": [], "summary": {}, "decision": "", "saved_path": "",
            "sentences": [], "posting": {**p, "evaluated": True}}


def draft(state: State) -> dict:
    raw = drafter.draft(state["posting"], state["profile"], state.get("banned"))
    return {"sentences": factcheck.check_all(raw, state["profile"])}


def check(state: State) -> dict:
    sentences = factcheck.check_all(state["sentences"], state["profile"])
    removed = [s["text"] for s in sentences if s["status"] == "remove"]
    rewrites = state.get("rewrites", 0) + (1 if removed else 0)
    return {"sentences": sentences, "summary": factcheck.summary(sentences),
            "banned": list(state.get("banned") or []) + removed, "rewrites": rewrites}


def after_check(state: State) -> str:
    has_removed = any(s["status"] == "remove" for s in state["sentences"])
    return "draft" if has_removed and state.get("rewrites", 0) <= MAX_REWRITES else "approve"


def approve(state: State) -> dict:
    answer = interrupt({"sentences": state["sentences"], "summary": state["summary"]})
    action = (answer or {}).get("action", "discard")
    sentences = (answer or {}).get("sentences") or state["sentences"]
    return {"decision": action, "sentences": factcheck.check_all(sentences, state["profile"])}


def after_approve(state: State) -> str:
    return "save" if state.get("decision") == "approve" else END


def save(state: State) -> dict:
    summary = factcheck.summary(state["sentences"])
    path = store.save_draft(state["posting"], state["sentences"], summary)
    store.add(state["posting"], stage="지원 준비")
    store.set_stage(state["posting"]["posting_id"], "지원 준비")
    return {"saved_path": str(path), "summary": summary}


def build_graph(checkpointer=None):
    g = StateGraph(State)
    g.add_node("evaluate", evaluate)
    g.add_node("draft", draft)
    g.add_node("check", check)
    g.add_node("approve", approve)
    g.add_node("save", save)
    g.add_edge(START, "evaluate")
    g.add_edge("evaluate", "draft")
    g.add_edge("draft", "check")
    g.add_conditional_edges("check", after_check, {"draft": "draft", "approve": "approve"})
    g.add_conditional_edges("approve", after_approve, {"save": "save", END: END})
    g.add_edge("save", END)
    return g.compile(checkpointer=checkpointer or MemorySaver())
'''

FILES['tests/test_agent.py'] = r'''from agent import drafter, factcheck, store
from agent.graph import build_graph
from langgraph.types import Command

POSTING = {"posting_id": "9", "title": "백엔드 개발자", "company": "X", "size": "TINY", "score": 4, "fit_score": 6,
           "have": ["Python"], "missing": ["Docker"], "duty": "Python Docker"}
PROFILE = {"major": "의료IT공학과", "coding_experience": "4년", "skills": ["Python"], "projects": []}


def test_factcheck_removes_unsupported_tech():
    out = factcheck.check_all([{"text": "Docker 로 배포했습니다.", "kind": "claim", "evidence": ""},
                               {"text": "Python 을 써봤습니다.", "kind": "claim", "evidence": ""}], PROFILE)
    assert out[0]["status"] == "remove" and out[1]["status"] == "ok"


def test_draft_has_todo_without_projects():
    assert any(s["kind"] == "todo" for s in drafter.draft(POSTING, PROFILE))


def test_graph_approve_saves_and_tracks(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DB", str(tmp_path / "t.db"))
    g = build_graph()
    cfg = {"configurable": {"thread_id": "t1"}}
    r = g.invoke({"posting": POSTING, "profile": PROFILE}, cfg)
    g.invoke(Command(resume={"action": "approve", "sentences": r["sentences"]}), cfg)
    assert (tmp_path / "drafts" / "9.md").exists()
    assert store.load_tracker()[0]["stage"] == "지원 준비"
    assert "Docker 등을" not in (tmp_path / "drafts" / "9.md").read_text(encoding="utf-8")   # 공고 문구 인용은 OK, 내 경험으로 쓰면 안 됨
'''

for name, text in FILES.items():
    p = Path(name)
    if p.exists():
        print("건너뜀(이미 있음):", name)
        continue
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")
    print("만들었음:", name)
