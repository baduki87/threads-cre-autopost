# 설정 가이드

키 4종을 발급받아 등록하는 순서. 하나씩 끝낼 때마다 점검 스크립트로 확인하면 된다.

```bash
./.venv/bin/python tools/check_setup.py
```

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
5. **권한(Permissions)** 에서 아래 두 개를 추가
   - `threads_basic`
   - `threads_content_publish`
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

시크릿을 다 넣었으면 **발행하지 않고** 결과물만 만들어본다.

1. GitHub 리포 → **Actions** 탭 → `매일 스레드 발행`
2. **Run workflow** → `발행하지 않고 결과물만 생성` **체크된 상태로** 실행
3. 실행이 끝나면 아래 **Artifacts** 에서 `post-output` 다운로드
4. 카드 이미지와 글이 마음에 드는지 확인

3~5일 이렇게 돌려보면서 `config/voice.md` 를 고친다. 납득되면 그대로 두면 된다 —
매일 아침 8시 스케줄 실행은 자동으로 실제 발행이다.
