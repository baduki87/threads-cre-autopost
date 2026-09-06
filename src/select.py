"""후보 선별: 중복 제거 → AI 스코어링 → 임계값 미달 시 백업 콘텐츠 전환.

메모가 있는 날은 이 단계를 건너뛴다 (draft.py 에서 처리).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import yaml

from . import state as state_mod
from .llm import ask_json
from .models import Article, Pick

KST = timezone(timedelta(hours=9))
SCORE_THRESHOLD = 6

SYSTEM = """당신은 서울 아파트 투자 콘텐츠의 편집장입니다.
독자는 서울 아파트에 실제로 돈을 넣거나 넣으려는 사람들입니다.

다음 기준으로 후보를 평가하세요.
- 실거주·투자 판단에 실제로 영향을 주는가
  (대출 규제, 세제, 재건축·재개발 인허가, 청약 제도, 공급 계획, 거래량)
- 구체적인 숫자나 일정이 있는가
- 관심이 큰 지역인가 (강남3구, 용산, 성동, 마포, 목동, 여의도 등)
- 단순 인사·동정·행사 공지, 지방 소규모 사업은 낮게 평가한다
- 상업용 부동산(오피스/물류/리테일)은 이 계정 주제가 아니므로 낮게 평가한다

10점 만점으로 매기되 후하게 주지 마세요.
평범한 소식은 4~5점, 진짜 의미 있는 것만 7점 이상입니다."""

PROMPT = """오늘의 후보 목록입니다.

{candidates}

가장 가치 있는 것 하나를 고르고 JSON 으로만 답하세요.

{{
  "index": <후보 번호, 쓸 만한 게 하나도 없으면 -1>,
  "score": <0-10 정수>,
  "reason": "<독자에게 왜 중요한지 2문장 이내. 기사 요약이 아니라 의미 해석>"
}}"""


def _format_candidates(articles: list[Article]) -> str:
    lines = []
    for i, a in enumerate(articles):
        when = a.published_at.astimezone(KST).strftime("%m-%d %H:%M") if a.published_at else "미상"
        lines.append(f"[{i}] ({a.source}, {when}) {a.title}\n    {a.snippet[:200]}")
    return "\n".join(lines)


def pick_fallback(path: str = "config/fallback.yaml",
                  st: dict | None = None) -> Pick:
    """백업 주제 하나. 최근에 쓴 주제를 피한다.

    예전에는 요일로 골랐는데 주제가 5개뿐이라 매주 같은 요일에 같은 주제가
    돌아왔다. 하루 3건이면 이틀에 한 바퀴라 더 빨리 뻔해진다.

    최근 제목에서 주제를 알아보려면 이력에 label 이 남아 있어야 한다.
    main._source_id 가 백업 글을 "[임장준비] ..." 형태로 기록하는 이유다.
    """
    with open(path, encoding="utf-8") as f:
        topics = yaml.safe_load(f)["topics"]

    recent = set()
    if st:
        # 최근 발행 제목에 들어간 분류를 훑어 같은 주제를 연달아 쓰지 않는다.
        recent = {t for t in state_mod.recent_titles(st, days=10)}

    unseen = [t for t in topics if not any(t["label"] in r for r in recent)]
    pool = unseen or topics
    topic = pool[datetime.now(KST).timetuple().tm_yday % len(pool)]

    return Pick(
        article=None,
        score=0,
        reason="쓸 만한 신규 소스가 없어 백업 콘텐츠로 전환했습니다.",
        fallback_topic=f"{topic['label']}|{topic['prompt']}",
    )


def select(articles: list[Article], st: dict) -> Pick:
    """오늘 쓸 소재 하나.

    하루 3건이지만 슬롯마다 별도 프로세스가 몇 시간 간격으로 돌고, 앞 슬롯이
    발행 직후 이력을 커밋한다. 그래서 '같은 배치 안의 중복' 을 따로 볼 필요가
    없다 — 앞 글의 기사 키와 제목이 이미 이력에 들어와 있다.
    다만 그러려면 이력에 **원본 기사**의 키·제목이 들어가야 한다(main._source_id).
    """
    seen = state_mod.seen_keys(st)
    previous = state_mod.recent_titles(st)

    fresh = [
        a for a in articles
        if a.key not in seen and not state_mod.is_near_duplicate(a.title, previous)
    ]
    print(f"[select] 후보 {len(articles)}건 → 중복 제거 후 {len(fresh)}건")

    if not fresh:
        return pick_fallback(st=st)

    result = ask_json(SYSTEM, PROMPT.format(candidates=_format_candidates(fresh)), effort="medium")
    idx = int(result.get("index", -1))
    score = int(result.get("score", 0))
    reason = str(result.get("reason", "")).strip()

    if idx < 0 or idx >= len(fresh) or score < SCORE_THRESHOLD:
        print(f"[select] 최고 점수 {score} < 임계값 {SCORE_THRESHOLD} → 백업 콘텐츠")
        return pick_fallback(st=st)

    chosen = fresh[idx]
    print(f"[select] 선정({score}점): {chosen.title[:60]}")
    return Pick(article=chosen, score=score, reason=reason)
