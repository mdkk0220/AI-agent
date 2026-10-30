import json

import pytest

from agent import drafter, factcheck, llm_drafter as ld

PROFILE = {"major": "의료IT공학과", "skills": {"언어": ["Python"], "웹": ["Flask"]},
           "projects": [{"name": "AI-agent", "summary": "공고 수집 에이전트", "my_role": "혼자 구현", "result": "테스트 17건 통과"}]}
POSTING = {"title": "AI 개발자", "company": "X", "duty": "LLM 서비스 개발과 Kubernetes 운영"}


def fake(sentences):
    return lambda prompt, key, model: json.dumps(sentences, ensure_ascii=False)


def test_parse_handles_code_fence_and_bad_items():
    txt = '```json\n[{"text":"a","kind":"claim","evidence":"x"}, 3, {"text":""}, {"text":"b","kind":"weird"}]\n```'
    out = ld.parse_response(txt)
    assert [s["text"] for s in out] == ["a", "b"]
    assert out[1]["kind"] == "claim"          # 처음 보는 kind 는 가장 엄격한 claim
    assert all(s["source"] == "llm" for s in out)


@pytest.mark.parametrize("bad", ["not json", "{}", "[]"])
def test_parse_raises_on_unusable(bad):
    with pytest.raises(ld.LlmUnavailable):
        ld.parse_response(bad)


def test_todo_sentence_becomes_todo_kind():
    out = ld.parse_response('[{"text":"[TODO: 사례 필요]","kind":"claim"}]')
    assert out[0]["kind"] == "todo"


def test_prompt_has_facts_but_not_name_or_email():
    p = ld.build_prompt(POSTING, {**PROFILE, "name": "성명규", "email": "a@b.c"}, ["지운 문장"])
    assert "Python" in p and "지운 문장" in p
    assert "성명규" not in p and "a@b.c" not in p


def test_no_key_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ld.LlmUnavailable):
        ld.draft(POSTING, PROFILE)


def test_empty_profile_raises(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    with pytest.raises(ld.LlmUnavailable):
        ld.draft(POSTING, {}, call=fake([{"text": "a", "kind": "claim"}]))


def test_draft_filters_banned(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    out = ld.draft(POSTING, PROFILE, ["a"], call=fake([{"text": "a", "kind": "claim"}, {"text": "b", "kind": "intro"}]))
    assert [s["text"] for s in out] == ["b"]


def test_dispatch_falls_back_to_template_and_says_why(monkeypatch):
    monkeypatch.setenv("DRAFTER", "llm")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    out = drafter.draft(POSTING, PROFILE)
    assert out and all(s["source"].startswith("template (LLM 실패") for s in out)


def test_template_is_default(monkeypatch):
    monkeypatch.delenv("DRAFTER", raising=False)
    assert all("source" not in s for s in drafter.draft(POSTING, PROFILE))


def test_factcheck_removes_invented_number_and_tech():
    inv = {"text": "Python 으로 3년간 서비스를 운영했습니다.", "kind": "claim", "evidence": ""}
    assert factcheck.check_sentence(inv, PROFILE)["status"] == "remove"
    k8s = {"text": "Kubernetes 클러스터를 운영해 보았습니다.", "kind": "claim", "evidence": ""}
    assert factcheck.check_sentence(k8s, PROFILE)["status"] == "remove"
    ok = {"text": "AI-agent 에서 테스트 17건을 통과시켰습니다.", "kind": "claim", "evidence": ""}
    assert factcheck.check_sentence(ok, PROFILE)["status"] == "ok"


def test_factcheck_numbers_ignored_for_motive():
    m = {"text": "공고의 24시간 운영 업무에 기여하고 싶습니다.", "kind": "motive", "evidence": ""}
    assert factcheck.check_sentence(m, PROFILE)["status"] == "ok"


def test_own_names_uses_profile_names_not_group_names():
    from agent.drafter import own_names
    out = own_names(["Django/FastAPI/Flask", "LangChain/LangGraph", "Python", "SQL"],
                    ["Python", "Flask", "LangGraph", "SQLite"])
    assert out == ["Flask", "LangGraph", "Python", "SQL"]
    assert "Django" not in " ".join(out)


def test_http_errors_have_helpful_messages(monkeypatch):
    class R:
        def __init__(self, code): self.status_code = code
    for code, word in ((404, "GEMINI_MODEL"), (403, "API 키"), (429, "429")):
        monkeypatch.setattr(ld.requests, "post", lambda *a, code=code, **k: R(code))
        with pytest.raises(ld.LlmUnavailable, match=word):
            ld.call_gemini("p", "k", "m")


def test_factcheck_blocks_tech_mixed_across_projects():
    prof = {"skills": {"a": ["Python", "PyTorch", "LangGraph", "Streamlit"]},
            "projects": [{"name": "AI-agent (취업 에이전트)", "stack": ["Python", "LangGraph", "Streamlit"]},
                         {"name": "knee-oa-classifier (X-ray)", "stack": ["Python", "PyTorch"], "my_role": "ResNet50 모델 구현"}]}
    mixed = {"text": "knee-oa-classifier 에서 LangGraph 와 PyTorch 를 활용했습니다.", "kind": "claim", "evidence": ""}
    r = factcheck.check_sentence(mixed, prof)
    assert r["status"] == "remove" and "LangGraph" in r["reason"]
    fine = {"text": "knee-oa-classifier 에서 PyTorch 로 ResNet50 을 구현했습니다.", "kind": "claim", "evidence": ""}
    assert factcheck.check_sentence(fine, prof)["status"] == "ok"
    two = {"text": "AI-agent 와 knee-oa-classifier 에서 Python 을 썼습니다.", "kind": "claim", "evidence": ""}
    assert factcheck.check_sentence(two, prof)["status"] == "ok"
