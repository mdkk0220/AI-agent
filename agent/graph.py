"""LangGraph 에이전트: 공고 평가 → 초안 → 팩트체크 → (필요하면 재작성, 최대 2회) → 사람 승인(interrupt) → 저장.

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
