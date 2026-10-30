import sqlite3

from classifier import evaluate as ev


def test_it_metrics():
    pairs = [(True, True), (True, True), (True, False), (False, True), (False, False), (False, False)]
    m = ev.it_metrics(pairs)
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (2, 1, 1, 2)
    assert m["accuracy"] == 4 / 6 and m["precision"] == 2 / 3 and m["recall"] == 2 / 3


def test_it_metrics_empty_and_no_division_by_zero():
    m = ev.it_metrics([])
    assert m["accuracy"] is None
    m = ev.it_metrics([(False, False)])
    assert m["precision"] is None and m["recall"] is None


def test_group_mapping():
    assert ev.to_rule_group("백엔드") == "웹 개발"
    assert ev.to_rule_group("AI·ML") == "AI·LLM 개발"
    assert ev.to_rule_group("보안") == "기타IT"
    m = ev.group_metrics([("백엔드", "웹 개발"), ("보안", "기타IT"), ("데이터", "웹 개발")])
    assert m["correct"] == 2 and m["n"] == 3


def test_evaluate_with_small_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE postings(posting_id TEXT, title TEXT, company_name TEXT, job_category TEXT);
        CREATE TABLE posting_details(posting_id TEXT, duty TEXT);
        INSERT INTO postings VALUES ('a','백엔드 개발자','X','dev'),('b','마케팅 매니저','Y','marketing'),('c','서비스 운영','Z','other');
    """)
    labels = [{"posting_id": "a", "is_it": "IT", "job_group": "백엔드"},
              {"posting_id": "b", "is_it": "비IT", "job_group": ""},
              {"posting_id": "c", "is_it": "IT", "job_group": "기타IT"},
              {"posting_id": "zz", "is_it": "IT", "job_group": "보안"}]  # DB 에 없음 → 제외
    r = ev.evaluate(conn, labels)
    assert r["it"]["n"] == 3
    assert r["it"]["fn"] == 1  # c: 정답은 IT 인데 규칙은 비IT
    assert r["group"]["n"] == 1 and r["group"]["correct"] == 1
