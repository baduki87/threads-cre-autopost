# 스레드 상업용 부동산 자동 발행

매일 상업용 부동산 뉴스와 국토교통부 보도자료를 수집해 요약하고,
카드 이미지와 함께 스레드에 자동 발행한다. 독자는 상업용 부동산 투자자·자산가.

```
수집 → 선별 → 요약·카피 → 카드 이미지 → 발행
```

## 구조

| 파일 | 역할 |
|---|---|
| `src/collect.py` | 국토부 보도자료 RSS + 네이버 뉴스 검색 API 수집 |
| `src/select.py` | 중복 제거 후 Claude 로 투자자 관점 스코어링, 상위 1건 선정 |
| `src/compose.py` | `config/voice.md` 를 주입해 훅·본문·관점 생성 |
| `src/card.py` | 1080×1350 카드 PNG 렌더링 (Pillow) |
| `src/publish.py` | Threads 발행 (컨테이너 생성 → 대기 → 발행), 토큰 갱신 |
| `src/main.py` | 파이프라인 오케스트레이션 |
| `config/voice.md` | **톤·관점 지침. 품질의 대부분을 여기가 결정한다** |
| `config/sources.yaml` | 키워드·제외어·수집 기간 |
| `config/fallback.yaml` | 쓸 만한 뉴스가 없는 날의 백업 콘텐츠 풀 |
| `state/published.json` | 발행 이력 (중복 방지) |

## 알아둘 제약

세 가지가 이 설계를 결정했다.

1. **Threads 는 이미지를 공개 URL 로만 받는다.** 로컬 파일 업로드가 불가능하다.
   그래서 카드를 `docs/img/` 에 커밋한 뒤 `raw.githubusercontent.com` URL 로 넘긴다.
   `PUBLIC_IMAGE_BASE` 를 설정하면 다른 호스팅을 쓸 수 있다.
2. **발행은 2단계다.** 컨테이너 생성 → 처리 완료 대기 → 발행. 바로 발행하면 실패한다.
3. **액세스 토큰은 약 60일 뒤 만료된다.** `refresh-token.yml` 이 주 1회 갱신한다.
   이걸 꺼두면 두 달 뒤 조용히 죽는다.

부수적으로, 국토부 사이트는 첫 요청에 307 + 쿠키 챌린지를 건다.
`requests.Session` 으로 쿠키를 물고 리다이렉트를 따라가야 본문을 받을 수 있다.

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
DRY_RUN=1 ./.venv/bin/python -m src.main
```

수집만 확인:

```bash
./.venv/bin/python -m src.collect
```

## GitHub Actions 설정

리포 시크릿(Settings → Secrets and variables → Actions):

| 이름 | 용도 |
|---|---|
| `ANTHROPIC_API_KEY` | 선별·카피 생성 |
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | 뉴스 검색 |
| `THREADS_ACCESS_TOKEN` / `THREADS_USER_ID` | 발행 |
| `REPO_ADMIN_TOKEN` | 토큰 갱신 워크플로가 시크릿을 다시 쓸 때 필요한 PAT (repo 스코프) |

변수(Variables)에 `THREADS_ACCOUNT_HANDLE` 를 넣으면 카드 하단에 계정명이 들어간다.

Threads 앱 권한은 `threads_basic`, `threads_content_publish` 가 필요하다
(2차 범위인 댓글 대응에는 `threads_read_replies`, `threads_manage_replies` 추가).

## 운영 순서

1. `workflow_dispatch` 로 **dry_run 체크한 상태**로 수동 실행 → 아티팩트에서 카드와 카피 확인
2. 3~5일 이 상태로 돌리며 `config/voice.md` 와 `config/sources.yaml` 조정
3. 품질이 납득되면 스케줄 실행(KST 08:00)에 맡긴다 — 스케줄 실행은 자동으로 실제 발행이다
4. 선별 임계값은 `src/select.py` 의 `SCORE_THRESHOLD` (기본 6)

쓸 만한 소스가 없는 날은 억지로 발행하지 않고 `config/fallback.yaml` 의
백업 콘텐츠로 전환한다. 낮은 품질을 매일 올리는 것보다 이쪽이 계정에 낫다.

## 2차 범위 (발행 안정화 후)

댓글 승인형 반자동 답글. 최근 글의 답글을 주기적으로 조회해 Claude 로 초안을
만들고, 텔레그램으로 보내 승인하면 발행한다. 부동산은 투자 자문 성격의 질문이
반드시 달리므로 완전 자동 답글은 쓰지 않는다.
