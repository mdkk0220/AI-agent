from matching import extras


def row(**kw):
    base = {c: "" for c in extras.COLS}
    base.update(kw)
    return base


def test_pay_and_place_from_labeled_lines():
    r = extras.extract(row(benefit="• 고용형태 : 정규직(수습 3개월) • 급여 : 면접 후 결정 • 근무지 : 서울 용산구 대사관로 • 직급"))
    assert r["pay"] == "면접 후 결정" and r["pay_kind"] == "협의"
    assert r["place"] == "서울 용산구 대사관로"


def test_amount_and_dash_separators():
    r = extras.extract(row(benefit="• 급여 : 연봉 6,000만원 ~ • 근무지 : 서울 마포구", hire_notes="- 근무장소: 서울시 강남구 도곡로3길 - 제출서류"))
    assert r["pay"] == "연봉 6,000만원 ~" and r["pay_kind"] == "금액"
    assert r["place"] == "서울 마포구"


def test_no_false_positive_on_plain_words():
    r = extras.extract(row(benefit="수습기간 (급여 100% 지급) 내 온보딩, 연봉 정보는 제거 후 제출, 도서 구매비 연간 50만원 한도"))
    assert r == {"pay": "", "pay_kind": "", "place": ""}


def test_work_colon_and_sentence_form():
    assert extras.extract(row(benefit="근무: 서울 도곡동 오피스. 주 4일 출근"))["place"].startswith("서울 도곡동 오피스")
    assert extras.extract(row(description="근무시간: 09:00–18:00"))["place"] == ""