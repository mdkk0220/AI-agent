"""로켓펀치 Open API 클라이언트 (공고 목록 + 공고 상세).

- 확인된 주소 (문서의 /api/v1/... 는 404, 실제는 /v1/...):
    목록  GET https://openapi.rocketpunch.com/v1/jobs
    상세  GET https://openapi.rocketpunch.com/v1/jobs/{jobId}   (본문: 주요 업무, 자격 요건, 우대 사항 등)
- 인증: X-RP-API-Key 헤더 (App Key, rp_app_ 로 시작)
- 목록: 페이지는 1부터, pageSize 최대 50. 공식 한도: 분당 60회, 하루 5,000회
- 오류 메시지에는 키/URL 을 절대 넣지 않는다.
"""
import time

import requests

BASE = "https://openapi.rocketpunch.com"
JOBS_URL = BASE + "/v1/jobs"
DETAIL_URL = BASE + "/v1/jobs/{}"
MAX_RETRY_AFTER = 60


class ApiError(Exception):
    def __init__(self, status: int, api_code: str = "", message: str = ""):
        super().__init__(f"HTTP {status} {api_code} {message}".strip())
        self.status, self.api_code, self.message = status, api_code, message


class AuthError(ApiError):
    """401/403: 키 문제 → 재시도해도 소용없음"""


class NotFound(ApiError):
    """404: 없는 공고(삭제/임시저장)"""


class RateLimited(ApiError):
    """429 를 재시도 횟수만큼 겪음"""


class TransientError(ApiError):
    """5xx / 네트워크 오류를 재시도 횟수만큼 겪음"""


def _body(r) -> dict:
    try:
        b = r.json()
        return b if isinstance(b, dict) else {}
    except ValueError:
        return {}


class Client:
    def __init__(self, app_key: str, delay: float = 1.5, retries: int = 3, session=None, timeout: int = 15, sleep=time.sleep):
        self._key = app_key
        self.delay, self.retries, self.timeout, self.sleep = delay, retries, timeout, sleep
        self.session = session or requests.Session()
        self._last = 0.0

    def _wait_turn(self):
        wait = self.delay - (time.time() - self._last)
        if wait > 0:
            self.sleep(wait)

    def _get(self, url: str, params: dict | None = None) -> dict:
        """GET 한 번(재시도 포함). 429/5xx/네트워크 오류는 재시도, 401/403 은 AuthError, 404 는 NotFound, 그 밖의 4xx 는 바로 ApiError."""
        last: ApiError | None = None
        for attempt in range(1, self.retries + 1):
            self._wait_turn()
            try:
                r = self.session.get(url, params=params, headers={"X-RP-API-Key": self._key}, timeout=self.timeout)
            except requests.RequestException as e:  # 예외 문자열에 URL 이 들어갈 수 있어 종류만 기록
                last = TransientError(0, "NETWORK", type(e).__name__)
                self._last = time.time()
                self.sleep(2 ** attempt)
                continue
            self._last = time.time()
            body = _body(r)
            code, msg = str(body.get("code", "")), str(body.get("message", ""))[:100]
            if r.status_code == 200:
                return body
            if r.status_code in (401, 403):
                raise AuthError(r.status_code, code, msg)
            if r.status_code == 404:
                raise NotFound(404, code, msg)
            if r.status_code == 429:
                last = RateLimited(429, code, msg)
                try:
                    wait = min(int(r.headers.get("Retry-After", "5")), MAX_RETRY_AFTER)
                except ValueError:
                    wait = 5
                self.sleep(wait)
                continue
            if r.status_code >= 500:
                last = TransientError(r.status_code, code, msg)
                self.sleep(2 ** attempt)
                continue
            raise ApiError(r.status_code, code, msg)  # 그 밖의 4xx: 재시도 무의미
        raise last or ApiError(0, "UNKNOWN", "")

    def search(self, keyword: str, page: int = 1, page_size: int = 50, **filters) -> dict:
        """목록 한 페이지."""
        params = {"keyword": keyword, "page": page, "pageSize": page_size, "sort": "DATE_DESC", **filters}
        body = self._get(JOBS_URL, params)
        if not isinstance(body.get("items"), list):
            raise ApiError(200, "BAD_SHAPE", "응답에 items 목록이 없음")
        return body

    def detail(self, job_id: str) -> dict:
        """공고 상세(본문 포함) 1건."""
        body = self._get(DETAIL_URL.format(job_id))
        if body.get("jobId") in (None, ""):
            raise ApiError(200, "BAD_SHAPE", "응답에 jobId 가 없음")
        return body


def normalize(item: dict) -> dict | None:
    """API 목록의 공고 1건 → postings 행. jobId 가 없으면 None."""
    job_id = item.get("jobId")
    if job_id in (None, ""):
        return None
    company = item.get("company") if isinstance(item.get("company"), dict) else {}
    join = lambda v: ",".join(str(x) for x in v) if isinstance(v, list) else str(v or "")
    return {
        "posting_id": f"rocketpunch:{job_id}",
        "source": "rocketpunch",
        "source_job_id": str(job_id),
        "title": str(item.get("title") or "").strip(),
        "subtitle": str(item.get("subtitle") or "").strip(),
        "job_category": str(item.get("jobCategory") or ""),
        "seniorities": join(item.get("seniorities")),
        "employment_types": join(item.get("employmentTypes")),
        "work_type": str(item.get("workType") or ""),
        "company_id": str(company.get("id") or ""),
        "company_name": str(company.get("name") or "").strip(),
        "company_industry": str(company.get("industry") or ""),
        "company_size": str(company.get("size") or ""),
        "end_at": str(item.get("endAt") or ""),
        "web_url": str(item.get("webUrl") or ""),
        "has_body": 0,  # 목록 API 는 본문을 주지 않음 (상세 수집 후 1로 바뀜)
    }


def normalize_detail(d: dict) -> dict:
    """상세 응답 → posting_details 행 (본문 필드)."""
    s = lambda v: "" if v is None else str(v)
    apply = d.get("applyMethod") if isinstance(d.get("applyMethod"), dict) else {}
    return {
        "status": s(d.get("status")),
        "hiring": 1 if d.get("hiring") else 0,
        "description": s(d.get("description")),
        "duty": s(d.get("duty")),
        "minimum_qualification": s(d.get("minimumQualification")),
        "preferred_qualification": s(d.get("preferredQualification")),
        "benefit": s(d.get("benefit")),
        "hire_process": s(d.get("hireProcess")),
        "hire_notes": s(d.get("hireNotes")),
        "apply_type": s(apply.get("type")),
        "apply_url": s(apply.get("url")),
    }