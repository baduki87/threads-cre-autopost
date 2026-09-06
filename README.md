# 스레드 부동산 자동 발행

부동산 뉴스와 국토교통부 보도자료를 수집해 요약하고, 카드 이미지와 함께
스레드에 **하루 3건** 자동 발행한다. 독자는 서울 아파트에 실제로 돈을 넣는 사람들.

```
수집 → 선별 → 요약·카피 → 카드 이미지 → 발행
```

## 하루 흐름

| KST | 워크플로 | 하는 일 |
|---|---|---|
| 07:00 | `insights.yml` | 3일 전 글의 조회수·좋아요 수집 |
| 08:00 | `auto-post.yml` | 초안 생성 + **바로 발행** (승인 없음) |
| 17:00 | `auto-post.yml` | 초안 생성 + **바로 발행** (승인 없음) |
| 19:00 | `draft.yml` | 초안을 노션 '대기' 로 올리고 카카오톡 알림 |
| 21:00 | `daily-post.yml` | 노션에서 **승인된 것만** 발행 |

시각은 계정 인사이트 실측(21~24시 1위, 15~18시 2위)에 맞췄다.
승인은 주력인 21시 한 번만 받는다 — 하루 세 번 승인은 지속되지 않고,
승인이 무너지면 자동화 전체가 멈춘다.

**메모가 있는 날은 21시가 가져간다.** 판단이 담긴 글은 사람 눈을 거쳐 나가야 한다.
08·17시 자동 슬롯은 `allow_memo=False` 라 메모를 건드리지 않는다.

### 같은 소재가 세 번 나가지 않게 하는 장치

슬롯마다 별도 프로세스가 몇 시간 간격으로 돈다. 앞 슬롯이 발행 직후
`state/published.json` 을 커밋하면 다음 슬롯이 그걸 읽고 제외한다.

그러려면 이력에 **원본 기사**의 키와 제목이 들어가야 한다. AI 가 다시 쓴 제목을
넣으면("성산시영 용적률 완화 시뮬레이션 결과가 나왔습니다") 원문
("용적률 1.2배 높이면 성산시영 분담금 1억 뚝")과 어순이 달라 비교가 헐거워진다.
`src/main.py` 의 `_source_id()` 가 이 구분을 맡는다.

19시 초안과 21시 발행은 프로세스가 다르고 노션 행에는 AI 제목만 있으므로,
`state/drafts.json` 에 원본 소재를 적어 두 단계를 잇는다.

## 구조

| 파일 | 역할 |
|---|---|
| `src/collect.py` | 국토부 보도자료 + 언론사 RSS 수집 |
| `src/select.py` | 이력 대조로 중복 제거 후 AI 스코어링, 1건 선정 |
| `src/compose.py` | `config/voice.md` 를 주입해 훅·본문·관점 생성 |
| `src/card.py` | 1080×1350 카드 PNG 렌더링 (Pillow) |
| `src/llm.py` | LLM 호출 래퍼. Gemini(무료) / Claude(유료) 전환 가능 |
| `src/notion.py` | 초안 승인·메모 입력 창구. 실패해도 발행을 막지 않는다 |
| `src/insights.py` | 발행 3일 뒤 조회수 수집 — 학습 루프를 닫는 조각 |
| `src/notify.py` | 카카오톡 알림. 실패해도 파이프라인을 멈추지 않는다 |
| `src/publish.py` | Threads 발행 (컨테이너 생성 → 대기 → 발행), 토큰 갱신 |
| `src/main.py` | 파이프라인 오케스트레이션 |
| `config/voice.md` | **톤·관점 지침. 품질의 대부분을 여기가 결정한다** |
| `config/sources.yaml` | 키워드·제외어·수집 기간 |
| `config/fallback.yaml` | 쓸 만한 뉴스가 없는 날의 백업 콘텐츠 풀 |
| `src/state.py` | 발행 이력. 슬롯 사이 중복 판정의 근거 |
| `state/published.json` | 발행 이력 (중복 방지, 슬롯별 성과 비교) |
| `state/drafts.json` | 19시 초안 → 21시 발행 사이에 원본 소재를 잇는 다리 |

## 알아둘 제약

세 가지가 이 설계를 결정했다.

1. **Threads 는 이미지를 공개 URL 로만 받는다.** 로컬 파일 업로드가 불가능하다.
   그래서 카드를 `docs/img/` 에 커밋한 뒤 `raw.githubusercontent.com` URL 로 넘긴다.
   `PUBLIC_IMAGE_BASE` 를 설정하면 다른 호스팅을 쓸 수 있다.
   리포가 **공개(public)** 여야 한다. 비공개 리포의 raw URL 은 외부에서 열 수 없어
   Threads 가 이미지를 가져가지 못한다.
2. **발행은 2단계다.** 컨테이너 생성 → 처리 완료 대기 → 발행. 바로 발행하면 실패한다.
   첫 댓글도 같은 흐름이고 `media_type=TEXT` + `reply_to_id` 만 다르다.
3. **액세스 토큰은 약 60일 뒤 만료된다.** `refresh-token.yml` 이 주 1회 갱신한다.
   이걸 꺼두면 두 달 뒤 조용히 죽는다.

부수적으로, 국토부 사이트는 첫 요청에 307 + 쿠키 챌린지를 건다.
`requests.Session` 으로 쿠키를 물고 리다이렉트를 따라가야 본문을 받을 수 있다.

## 설정

키 발급 방법은 [docs/SETUP.md](docs/SETUP.md) 에 단계별로 정리했다.
준비 상태는 아래 명령으로 언제든 확인할 수 있다.

```bash
./.venv/bin/python tools/check_setup.py
```

## 로컬 실행

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
```

API 키 없이 파이프라인 전체를 검증한다 (LLM 만 스텁으로 대체):

```bash
./.venv/bin/python tools/smoke_test.py
```

실제 키로 발행 직전까지 돌린다. 결과는 `out/` 에 남는다:

```bash
DRY_RUN=1 MODE=auto SLOT=08 ./.venv/bin/python -m src.main
```

`MODE` 는 `auto`(자동 발행) / `draft`(노션 초안) / `publish`(승인분 발행).
`SLOT` 은 카드 파일명과 성과 기록에 쓴다 — 안 넣으면 현재 시각에서 가장 가까운
슬롯을 고른다. 하루 3건이 같은 파일명을 쓰면 앞 글의 이미지가 덮어써진다.

수집만 확인:

```bash
./.venv/bin/python -m src.collect
```

## GitHub Actions 설정

리포 시크릿(Settings → Secrets and variables → Actions):

| 이름 | 용도 |
|---|---|
| `GEMINI_API_KEY` **또는** `ANTHROPIC_API_KEY` | 선별·카피 생성. Gemini 는 무료 등급이 있다 |
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | (선택) 네이버 뉴스 검색. 2026-07 신규 신청이 막혀 RSS 로 대체했다 |
| `NOTION_TOKEN` / `NOTION_DB_ID` | 초안 승인·메모 |
| `KAKAO_REST_API_KEY` / `KAKAO_REFRESH_TOKEN` / `KAKAO_CLIENT_SECRET` | 카카오톡 알림 |
| `THREADS_ACCESS_TOKEN` / `THREADS_USER_ID` | 발행 |
| `REPO_ADMIN_TOKEN` | 토큰 갱신 워크플로가 시크릿을 다시 쓸 때 필요한 PAT (repo 스코프) |

변수(Variables)에 `THREADS_ACCOUNT_HANDLE` 를 넣으면 카드 하단에 계정명이 들어간다.

Threads 앱 권한은 `threads_basic`, `threads_content_publish`,
`threads_manage_insights` 가 필요하다
(2차 범위인 댓글 대응에는 `threads_read_replies`, `threads_manage_replies` 추가).

## 운영 순서

1. `workflow_dispatch` 로 **dry_run 체크한 상태**로 수동 실행 → 아티팩트에서 카드와 카피 확인
2. 3~5일 이 상태로 돌리며 `config/voice.md` 와 `config/sources.yaml` 조정
3. 품질이 납득되면 스케줄에 맡긴다 (위 '하루 흐름') — 스케줄 실행은 자동으로 실제 발행이다
4. 선별 임계값은 `src/select.py` 의 `SCORE_THRESHOLD` (기본 6)

쓸 만한 소스가 없는 날은 억지로 발행하지 않고 `config/fallback.yaml` 의
백업 콘텐츠로 전환한다. 낮은 품질을 매일 올리는 것보다 이쪽이 계정에 낫다.

## 2주 뒤 점검할 것

팔로워 486명에 하루 3건은 공격적이다. 90일에 8건 쓰던 계정의 30배다.
`state/published.json` 의 `slot` 별 조회수를 비교해 **08시 슬롯을 유지할지** 정한다
(08시는 실측 근거가 약한, 뉴스 신선도만 보고 넣은 슬롯이다).
팔로워가 줄면 2건으로 되돌린다.

## 2차 범위 (발행 안정화 후)

댓글 승인형 반자동 답글. 최근 글의 답글을 주기적으로 조회해 Claude 로 초안을
만들고, 텔레그램으로 보내 승인하면 발행한다. 부동산은 투자 자문 성격의 질문이
반드시 달리므로 완전 자동 답글은 쓰지 않는다.
