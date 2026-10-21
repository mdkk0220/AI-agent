"""로켓펀치 Open API 확인 스크립트: 키가 되는지, 응답이 어떤 구조인지 본다.

    python -m collector.check_rocketpunch            # 기본 검색어 '백엔드'
    python -m collector.check_rocketpunch 데이터

출력에는 키도, 공고의 실제 값도 나오지 않는다 (필드 이름·타입·글자 수만 출력).
그래서 출력 결과를 그대로 복사해서 공유해도 안전하다.
응답 원본은 data/samples/rocketpunch_sample.json 에 저장된다 (git 에 올라가지 않음).

확인하려는 것
  1. 키/헤더가 맞는가 (HTTP 상태)
  2. 한 페이지에 몇 건이고, 전체 몇 건인가 (페이지네이션)
  3. 공고 1건에 어떤 필드가 있는가
  4. 본문(긴 글) 필드가 있는가
  5. 호출 한도 헤더가 오는가
"""
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
# 공식 문서의 주소와, 실제 서버 응답(details: api/api/v1/jobs)을 보고 추정한 주소를 차례로 시도한다.
ENDPOINTS = [
    "https://openapi.rocketpunch.com/api/v1/jobs",
    "https://openapi.rocketpunch.com/v1/jobs",
]
ENDPOINT = ENDPOINTS[0]
LONG_TEXT = 300  # 이 글자 수 이상이면 '본문 후보'로 표시


def describe(x, indent=0, key="", long_fields=None, path=""):
    """값은 숨기고 구조만 출력한다. 긴 문자열 필드는 long_fields 에 모은다."""
    pad = "  " * indent
    if isinstance(x, dict):
        print(f"{pad}{key}{{}} ({len(x)}개 키)")
        for k, v in x.items():
            describe(v, indent + 1, f"{k}: ", long_fields, f"{path}.{k}" if path else k)
    elif isinstance(x, list):
        print(f"{pad}{key}[{len(x)}개]")
        if x:
            describe(x[0], indent + 1, "(첫 항목) ", long_fields, f"{path}[]")
    elif isinstance(x, str):
        print(f"{pad}{key}str ({len(x)}자)")
        if long_fields is not None and len(x) >= LONG_TEXT:
            long_fields.append((path, len(x)))
    elif x is None:
        print(f"{pad}{key}null")
    else:
        print(f"{pad}{key}{type(x).__name__}")


def _print_error_body(r) -> None:
    """에러 응답의 code/message/details 를 보여 준다 (에러 본문에는 키가 들어 있지 않다)."""
    try:
        body = r.json()
    except ValueError:
        return
    if isinstance(body, dict):
        for k in ("code", "message", "details"):
            if k in body:
                print(f"    {k}: {str(body[k])[:120]}")


def main(argv=None) -> int:
    load_dotenv(ROOT / ".env")
    keyword = (argv or sys.argv[1:] or ["백엔드"])[0]
    key = os.getenv("ROCKETPUNCH_APP_KEY", "").strip()
    if not key:
        print("ROCKETPUNCH_APP_KEY 가 .env 에 없습니다. .env.example 을 .env 로 복사한 뒤 App Key 를 넣으세요.")
        return 2
    if key.startswith("rp_sec_"):
        print("Secret key(rp_sec_)가 들어 있습니다. 콘솔에서 App Key(rp_app_ 로 시작)를 찾아 넣으세요.")
        return 2
    if not key.startswith("rp_app_"):
        print("키가 rp_app_ 로 시작하지 않습니다. 복사할 때 앞뒤 공백이나 잘림이 없는지 확인하세요.")
        return 2

    r = None
    for url in ENDPOINTS:
        try:
            r = requests.get(url, params={"keyword": keyword}, headers={"X-RP-API-Key": key}, timeout=15)
        except requests.RequestException as e:  # 예외 문자열에 URL 이 들어갈 수 있어 종류만 출력
            print(f"네트워크 오류: {type(e).__name__}")
            return 1
        print(f"[시도] {url} → HTTP {r.status_code}")
        if r.status_code != 404:
            print(f"✔ 동작하는 주소: {url}  ← 이 주소를 수집 코드에 사용합니다\n")
            break
        _print_error_body(r)

    print(f"HTTP {r.status_code}  (검색어: {keyword})")
    remaining = r.headers.get("X-RP-RateLimit-Remaining")
    if remaining is not None:
        print(f"분당 남은 호출 수 헤더: {remaining}")
    if r.status_code == 429:
        print(f"호출 한도 초과. {r.headers.get('Retry-After', '?')}초 뒤에 다시 시도하세요.")
        return 1
    if r.status_code == 401:
        print("키가 유효하지 않거나 헤더가 잘못됐습니다. 키 오타·공백을 확인하세요.")
        return 1
    if r.status_code == 403:
        print("키는 유효하지만 이 리소스에 대한 권한이 없습니다.")
        return 1
    if r.status_code >= 400:
        print("요청이 실패했습니다. 위의 에러 내용(code/message/details)을 알려 주세요.")
        return 1

    try:
        data = r.json()
    except ValueError:
        print(f"JSON 이 아닌 응답입니다 (길이 {len(r.text)}자).")
        return 1

    out = ROOT / "data" / "samples"
    out.mkdir(parents=True, exist_ok=True)
    (out / "rocketpunch_sample.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n[페이지네이션]")
    for k in ("totalItems", "totalPages", "page", "pageSize"):
        if isinstance(data, dict) and k in data:
            print(f"  {k}: {data[k]}")
    items = data.get("items") if isinstance(data, dict) else None
    print(f"  이번 응답의 공고 수: {len(items) if isinstance(items, list) else '확인 불가'}")

    print("\n[응답 구조 (값은 숨김)]")
    long_fields: list = []
    describe(data, long_fields=long_fields)

    print("\n[본문 후보 (300자 이상 문자열 필드)]")
    if long_fields:
        for p, n in long_fields:
            print(f"  {p}: {n}자")
    else:
        print("  없음 → 본문이 응답에 없을 가능성이 높습니다 (상세 조회용 별도 엔드포인트가 있는지 문서 확인 필요).")

    print("\n원본 저장: data/samples/rocketpunch_sample.json (git 에 올라가지 않음)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())