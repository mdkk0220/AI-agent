"""공고 본문에서 급여·근무지 문구를 꺼낸다 (본문에 적힌 문구 그대로, 숫자 계산이나 추측은 하지 않는다).

API 에는 급여·지역 필드가 없고, 일부 공고만 본문에 "급여: ...", "근무지: ..." 형태로 적는다.
라벨 뒤에 콜론이 있는 경우만 뽑는다 (단어가 우연히 들어간 문장 오탐을 피하려고).
"""
import re

SEP = re.compile(r"\s*(?:[•·●▶■※*]|\s-\s|\s/\s(?=[가-힣A-Za-z]+\s*[:：])|\|)\s*")  # 항목 구분 기호
PAY_RX = re.compile(r"(?:급여|연봉|보수|월급)(?:\s*(?:조건|수준|형태))?\s*[:：]\s*(.+)")
PLACE_RX = re.compile(r"(?:근무\s*지(?:역)?|근무\s*장소|근무\s*위치|근무)\s*[:：]\s*(.+)")
NEGOTIABLE = ("협의", "면접", "내규", "추후")
MAX_LEN = 45
COLS = ("benefit", "hire_notes", "description", "minimum_qualification", "duty")


def _clip(s: str) -> str:
    s = SEP.split(s.strip(), maxsplit=1)[0].strip(" :-·")
    return s[:MAX_LEN].rstrip()


def _find(rx, texts):
    for t in texts:
        text = " ".join((t or "").split())
        for m in rx.finditer(text):
            out = _clip(m.group(1))
            if out:
                return out
    return ""


def extract(row) -> dict:
    texts = [row[c] if c in row.keys() else "" for c in COLS]
    pay = _find(PAY_RX, texts)
    kind = ""
    if pay:
        kind = "협의" if any(w in pay for w in NEGOTIABLE) else "금액"
    return {"pay": pay, "pay_kind": kind, "place": _find(PLACE_RX, texts)}