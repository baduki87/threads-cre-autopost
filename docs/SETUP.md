# 설정 가이드

키를 발급받아 등록하는 순서. 하나씩 끝낼 때마다 점검 스크립트로 확인하면 된다.

```bash
./.venv/bin/python tools/check_setup.py
```

## 키를 어디에 넣나

`.env` 파일에 한 번만 적어두면 된다. 터미널을 새로 열 때마다 다시 입력할 필요가 없다.

```bash
cp .env.example .env
```

그리고 `.env` 를 열어 값을 채운다. **이 파일은 깃허브에 올라가지 않는다**
(`.gitignore` 에 등록돼 있음). 아래 안내의 `export ...` 대신 이 방법을 써도 된다.

---

## 1. 글을 써주는 AI — 무료 또는 유료

이 프로그램에서 **돈이 드는 부분은 여기 하나뿐이다.** 나머지는 전부 무료다.
두 가지 중 하나만 고르면 된다. 나중에 바꿔도 코드는 안 건드려도 된다.

### 방법 A — Gemini (무료, 신용카드 불필요) ← 추천

1. https://aistudio.google.com/apikey 접속 → 구글 계정으로 로그인
2. **Create API key** 클릭
3. 나온 키를 복사

```bash
export GEMINI_API_KEY="복사한키"
./.venv/bin/python tools/check_setup.py
```

무료 등급은 flash 계열 모델만 열려 있는데, 우리는 하루에 2번만 호출하므로
한도에 걸릴 일이 없다. 모델명은 자주 바뀌므로 코드가 **쓸 수 있는 모델을
직접 조회해서 최신 flash 를 자동으로 고른다.** 직접 지정하고 싶으면
`GEMINI_MODEL` 환경변수를 쓰면 된다.

지금 어떤 모델을 쓸 수 있는지 보려면:

```bash
./.venv/bin/python -m src.llm
```

> 무료 등급은 보낸 내용이 구글 모델 학습에 쓰일 수 있다.
> 우리가 보내는 건 이미 공개된 뉴스 기사라 문제되지 않는다.

### 방법 B — Claude (유료, 품질 우선)

글의 "관점" 부분 품질을 더 끌어올리고 싶을 때. 최소 충전 금액은 US$5.

1. https://console.anthropic.com → **API keys** → **Create Key**
2. 결제 수단 등록 (Billing)

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
./.venv/bin/python tools/check_setup.py
```

하루 1건 발행 기준으로 한 달에 몇 백 원~2천 원 수준이라, US$5 를 넣으면
몇 달은 간다. 다만 **무료가 목표라면 방법 A 로 충분하다.**

### 둘 다 넣으면?

Claude 가 우선 사용된다. 강제로 고르려면:

```bash
export LLM_PROVIDER=gemini   # 또는 claude
```

---

## 2. 네이버 검색 API (뉴스를 모아오는 부분)

무료다. 하루 25,000회까지 쓸 수 있는데 우리는 하루 10회 정도만 쓴다.

1. https://developers.naver.com/apps/#/register 접속 → 네이버 로그인
2. **애플리케이션 이름**: 아무거나 (예: 스레드자동발행)
3. **사용 API**: `검색` 선택
4. **환경 추가**: `WEB 설정` 선택 → 서비스 URL 에 `http://localhost` 입력
5. 등록하면 **Client ID** 와 **Client Secret** 이 나온다

```bash
export NAVER_CLIENT_ID="..."
export NAVER_CLIENT_SECRET="..."
./.venv/bin/python tools/check_setup.py
```

이게 없어도 국토부 보도자료만으로 돌아가지만, 소재가 훨씬 적어진다.

---

## 3. Threads 액세스 토큰 (실제로 올리는 부분)

가장 복잡하다. 시간을 넉넉히 잡을 것.

1. https://developers.facebook.com 접속 → 페이스북 계정으로 로그인
2. 우측 상단 **내 앱** → **앱 만들기**
3. 사용 사례에서 **Threads API 사용** 선택
4. 앱이 만들어지면 **Threads API** 설정으로 이동
5. **권한(Permissions)** 에서 아래 세 개를 추가
   - `threads_basic`
   - `threads_content_publish`
   - `threads_manage_insights`  ← 조회수 수집에 필요. 빠지면 학습 루프가 안 돈다
6. 발행할 스레드 계정을 앱에 연결 (테스터로 추가 후 수락)
7. **액세스 토큰 생성** → 나온 토큰 복사
8. **단기 토큰이면 장기 토큰으로 교환해야 한다** (단기는 1시간 만에 만료)

토큰과 함께 **User ID** 도 필요하다. 토큰을 받았다면 이렇게 확인할 수 있다:

```bash
curl -s "https://graph.threads.net/v1.0/me?fields=id,username&access_token=토큰붙여넣기"
```

나온 `id` 가 `THREADS_USER_ID` 다.

```bash
export THREADS_ACCESS_TOKEN="..."
export THREADS_USER_ID="..."
./.venv/bin/python tools/check_setup.py
```

> 이 토큰은 약 60일 뒤 만료된다. `refresh-token.yml` 워크플로가 주 1회 자동 갱신하므로
> 한 번만 제대로 넣어두면 이후엔 신경 쓰지 않아도 된다.

---

## 3.5 노션 (초안 승인 + 메모 입력)

하루 흐름의 중심이다. 저녁 7시에 초안이 여기 올라오고, 승인하면 밤 9시에 발행된다.
임장 다녀와서 메모를 넣는 곳도 여기다.

### 통합 토큰 만들기

1. https://www.notion.so/my-integrations → **New integration**
2. 이름 아무거나 (예: 스레드자동발행), 워크스페이스 선택
3. **Internal Integration Secret** 복사 (`ntn_...` 또는 `secret_...`)

### DB — 이미 만들어져 있다

**스레드 자동 발행** DB 를 만들어뒀다.
https://www.notion.so/bcb85698aaa5474e9c4d5a5f5716dc1f

`NOTION_DB_ID` 는 `bcb85698aaa5474e9c4d5a5f5716dc1f` 다.

직접 다시 만들 일이 생기면 아래 속성을 **이름 그대로** 추가한다.
이름이 하나라도 다르면 코드가 못 찾는다.

| 속성 이름 | 타입 | 비고 |
|---|---|---|
| 제목 | 제목 | 기본으로 있음 |
| 상태 | 선택 | 값: `메모` `대기` `승인` `발행됨` `보류` |
| 본문 | 텍스트 | **여기를 고치면 고친 대로 발행된다** |
| 상세 | 텍스트 | 발행 직후 **첫 댓글**로 붙는다. 본문 3줄에 못 담은 현장 정보 |
| 유형 | 선택 | 값: `임장기` `방법론` `질문` `뉴스` `단상` |
| 카드 | URL | 카드 이미지 링크 |
| 발행일 | 날짜 | |
| post_id | 텍스트 | 성과 수집용 |
| 조회수 | 숫자 | 자동으로 채워짐 |
| 좋아요 | 숫자 | 자동으로 채워짐 |
| 댓글 | 숫자 | 자동으로 채워짐 |
| 메모 | 텍스트 | **폰에서 적는 곳** |

### 통합을 DB 에 연결하기 ← 빼먹기 쉬움

DB 페이지 우상단 `⋯` → 맨 아래 **연결** → 방금 만든 통합 선택.
**이걸 안 하면 토큰이 맞아도 접근이 거부된다.**

### 확인

```bash
export NOTION_TOKEN="ntn_..."
export NOTION_DB_ID="bcb85698aaa5474e9c4d5a5f5716dc1f"
./.venv/bin/python tools/check_setup.py
```

`✅ 노션` 이 뜨면 속성 이름까지 맞게 만든 것이다.

### 쓰는 법

| 하고 싶은 것 | 하는 법 |
|---|---|
| 임장 메모 남기기 | 새 행 추가 → `상태 = 메모`, `메모` 칸에 몇 줄 적기 |
| 초안 승인 | 저녁에 `대기` 행 확인 → 본문·상세 손보고 `상태 = 승인` |
| 오늘 쉬기 | 아무것도 안 함. 승인이 없으면 발행되지 않는다 |

---

## 3.7 카카오톡 알림 (선택이지만 강력히 권함)

이게 없으면 **실패해도 조용히 지나가고, 승인도 깜빡하게 된다.**
저녁 7시에 "초안 나왔습니다" 가 폰으로 오고, 어딘가 실패하면 바로 알려준다.

카카오는 절차가 번거로워서 도우미 스크립트를 만들어뒀다.

```bash
./.venv/bin/python tools/kakao_setup.py
```

화면 안내를 따라가면 된다. 요약하면:

1. https://developers.kakao.com/console/app → 앱 만들기
2. **REST API 키** 복사
3. [카카오 로그인] 활성화 ON + Redirect URI 에 `https://example.com/oauth` 등록
4. [동의항목] → **카카오톡 메시지 전송** 을 선택 동의로
5. 스크립트가 준 주소를 브라우저에 붙여넣고 동의 → **주소창 전체를 복사해서 붙여넣기**

끝나면 `.env` 에 넣을 두 줄을 알려준다.

```bash
./.venv/bin/python -m src.notify
```

카카오톡 '나와의 채팅' 에 테스트 메시지가 오면 성공이다.

> refresh_token 은 약 2개월마다 갱신된다. 새 토큰이 발급되면 로그에
> "KAKAO_REFRESH_TOKEN 시크릿을 갱신하세요" 가 뜬다.

---

## 4. GitHub 리포지토리

Actions 로 매일 자동 실행하고, 카드 이미지를 인터넷에 공개하는 역할을 한다.

```bash
gh repo create 리포이름 --public --source=. --push
```

> **공개(public) 리포여야 한다.** Threads 는 이미지를 인터넷 주소로만 받는데,
> 비공개 리포의 이미지 주소는 외부에서 열 수 없어 발행이 실패한다.
> 코드를 공개하고 싶지 않다면 이미지 전용 공개 리포를 따로 만들고
> `PUBLIC_IMAGE_BASE` 환경변수로 지정하는 방법이 있다.

리포를 만든 뒤 시크릿 등록:

```bash
gh secret set GEMINI_API_KEY        # 무료로 쓸 경우
# gh secret set ANTHROPIC_API_KEY   # 유료로 쓸 경우
gh secret set NAVER_CLIENT_ID
gh secret set NAVER_CLIENT_SECRET
gh secret set THREADS_ACCESS_TOKEN
gh secret set THREADS_USER_ID
gh secret set NOTION_TOKEN
gh secret set NOTION_DB_ID
gh secret set KAKAO_REST_API_KEY
gh secret set KAKAO_REFRESH_TOKEN
```

각 명령을 치면 값을 입력하라고 나온다. 붙여넣고 엔터.

계정명을 카드에 넣으려면:

```bash
gh variable set THREADS_ACCOUNT_HANDLE --body "@내계정명"
```

토큰 자동 갱신을 쓰려면 PAT 가 하나 더 필요하다
(https://github.com/settings/tokens → `repo` 스코프로 생성):

```bash
gh secret set REPO_ADMIN_TOKEN
```

---

## 5. 첫 실행

시크릿을 다 넣었으면 **발행하지 않고** 초안만 만들어본다.

1. GitHub 리포 → **Actions** 탭 → `저녁 초안 생성`
2. **Run workflow** → `노션에 쓰지 않고 결과물만 생성` **체크된 상태로** 실행
3. **Artifacts** 에서 `draft-output` 다운로드 → 카드와 글 확인

글이 마음에 들면 체크를 **해제**하고 다시 실행한다. 노션에 `대기` 행이 생긴다.
승인해두고 `밤 9시 발행` 을 수동 실행하면 실제로 올라간다.

3~5일 이렇게 돌려보며 `config/voice.md` 를 고친다.
납득되면 그대로 두면 된다 — 스케줄이 알아서 돈다.

## 하루 스케줄 정리

| 시각 (KST) | 워크플로 | 하는 일 |
|---|---|---|
| 19:00 | `저녁 초안 생성` | 메모/뉴스로 초안 → 노션 `대기` |
| — | (회원님) | 노션에서 확인 → `승인` |
| 21:00 | `밤 9시 발행` | 승인된 것만 발행 |
| 08:00 | `성과 수집` | 3일 지난 글 조회수 수집 → 다음 초안이 학습 |
