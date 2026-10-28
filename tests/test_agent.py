from agent import drafter, factcheck, store
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
