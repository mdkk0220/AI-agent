# 실행 절차 (runbook)

## 승인 메일이 왔을 때

1. 신청 때 적은 이메일의 받은편지함·스팸함에서 사람인 승인 메일을 확인한다.
2. `oapi.saramin.co.kr`에 로그인 → `[Application] > [앱 등록]`으로 앱을 만든다 (이름 예: `AI-agent`).
3. `[Application] > [내 앱리스트]`에서 앱 이름을 눌러 access-key를 확인한다.
4. 프로젝트 폴더에서 `.env.example`을 `.env`로 복사하고 `SARAMIN_ACCESS_KEY=` 뒤에 키를 붙여 넣는다.
   - 키를 채팅, 깃허브, 스크린샷에 노출하지 않는다 (이용 조건상 공유 금지).
   - 키가 노출됐다면 사람인 사이트에서 앱을 다시 만들거나 문의한다.
5. 응답 구조 확인 → 첫 수집 → 자동 실행 등록 (수집 코드 완성 후, 아래 참고).

## 환경 준비

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # Windows: copy .env.example .env
```

## 하루 1회 자동 실행 (수집 코드 완성 후)

- **Windows:** 작업 스케줄러 → 기본 작업 만들기 → 매일 → 프로그램: `scripts\run_daily.bat`
  - PC가 꺼져 있던 날은 수집이 빠집니다. 작업 속성에서 "예약된 시작 시간을 놓친 경우 가능한 한 빨리 작업 시작"을 켜 두세요.
- **macOS/Linux:** `crontab -e` 에 `10 9 * * * /경로/AI-agent/scripts/run_daily.sh`
- PC가 자주 꺼진다면 GitHub Actions 같은 클라우드 실행도 가능하지만, DB 보관 방식을 따로 설계해야 합니다.

## 매일 확인 (10분)

- 수집 성공 여부, 수신·신규 건수
- 0건이거나 전날 대비 크게 줄었는지
- 에러 코드 `4`(일일 한도 초과)가 있었는지
- DB 백업 파일이 생겼는지

## 백업

- 매일 DB 파일을 `data/backups/`에 복사하고 최근 14개만 보관
- 마감된 공고는 다시 못 구하므로, 가끔 `data/` 폴더를 다른 곳(외장 디스크, 클라우드 드라이브)에도 복사한다. 단, 공개 저장소에는 올리지 않는다.

## 커밋 전 체크

```bash
git status                       # .env, data/, profile.yaml 이 목록에 없어야 함
git diff --cached --stat
```

- 키가 한 번이라도 커밋에 들어갔다면 **히스토리에서 지워도 이미 노출된 것으로 보고** 키를 폐기·재발급한다.
