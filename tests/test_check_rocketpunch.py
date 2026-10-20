import json

import pytest
import requests

from collector import check_rocketpunch as cr

KEY = "rp_app_SECRET_TEST_KEY_123"


class FakeResp:
    def __init__(self, status=200, data=None, headers=None, text=""):
        self.status_code, self._data, self.headers, self.text = status, data, headers or {}, text

    def json(self):
        if self._data is None:
            raise ValueError
        return self._data


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(cr, "ROOT", tmp_path)  # data/samples 와 .env 탐색 위치를 임시 폴더로
    monkeypatch.setenv("ROCKETPUNCH_APP_KEY", KEY)


def run(monkeypatch, capsys, resp=None, exc=None, argv=None):
    def fake_get(url, params=None, headers=None, timeout=None):
        assert headers == {"X-RP-API-Key": KEY} and url == cr.ENDPOINT
        if exc:
            raise exc
        return resp

    monkeypatch.setattr(cr.requests, "get", fake_get)
    code = cr.main(argv or ["백엔드"])
    return code, capsys.readouterr().out


def test_success_prints_structure_never_values_or_key(monkeypatch, capsys, tmp_path):
    secret_title = "아주비밀스러운공고제목"
    data = {"items": [{"id": 1, "title": secret_title, "description": "가" * 500, "tags": ["a", "b"], "salary": None}],
            "totalItems": 321, "totalPages": 33, "page": 1, "pageSize": 10}
    code, out = run(monkeypatch, capsys, FakeResp(200, data, {"X-RP-RateLimit-Remaining": "58"}))
    assert code == 0
    assert KEY not in out and secret_title not in out        # 키·실제 값은 출력되지 않음
    assert "totalItems: 321" in out and "이번 응답의 공고 수: 1" in out
    assert "분당 남은 호출 수 헤더: 58" in out
    assert "items[].description: 500자" in out               # 본문 후보 탐지
    assert (tmp_path / "data" / "samples" / "rocketpunch_sample.json").exists()
    assert json.loads((tmp_path / "data/samples/rocketpunch_sample.json").read_text(encoding="utf-8"))["totalItems"] == 321


def test_no_long_text_reports_body_missing(monkeypatch, capsys):
    data = {"items": [{"id": 1, "title": "짧음"}], "totalItems": 1, "totalPages": 1, "page": 1, "pageSize": 10}
    _, out = run(monkeypatch, capsys, FakeResp(200, data))
    assert "본문이 응답에 없을 가능성" in out


@pytest.mark.parametrize("status,msg", [(401, "유효하지 않"), (403, "권한이 없"), (429, "호출 한도 초과")])
def test_http_errors_have_clear_messages(monkeypatch, capsys, status, msg):
    code, out = run(monkeypatch, capsys, FakeResp(status, headers={"Retry-After": "7"}))
    assert code == 1 and msg in out and KEY not in out


def test_network_error_does_not_leak_key(monkeypatch, capsys):
    code, out = run(monkeypatch, capsys, exc=requests.ConnectionError(f"failed ... {KEY}"))
    assert code == 1 and KEY not in out and "ConnectionError" in out


def test_non_json_response(monkeypatch, capsys):
    code, out = run(monkeypatch, capsys, FakeResp(200, None, text="<html>x</html>"))
    assert code == 1 and "JSON 이 아닌" in out


@pytest.mark.parametrize("bad,msg", [("", "없습니다"), ("rp_sec_abc", "Secret key"), ("abc123", "rp_app_ 로 시작하지 않습니다")])
def test_key_format_checks_without_calling_api(monkeypatch, capsys, bad, msg):
    monkeypatch.setenv("ROCKETPUNCH_APP_KEY", bad)
    monkeypatch.setattr(cr.requests, "get", lambda *a, **k: pytest.fail("API 를 호출하면 안 됨"))
    code = cr.main(["x"])
    out = capsys.readouterr().out
    assert code == 2 and msg in out
    assert bad == "" or bad not in out  # 잘못된 키 값도 출력하지 않음
