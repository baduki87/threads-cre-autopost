"""후보 선별: 중복 제거 → Claude 스코어링 → 임계값 미달 시 백업 콘텐츠 전환."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import yaml

from . import state as state_mod
from .llm import ask_json
from .models import Article, Pick

KST = timezone(timedelta(hours=9))
SCORE_THRESHOLD = 6

SYSTEM = """당신은 상업용 부동산 투자 콘텐츠의 편집장입니다.
독자는 상업용 부동산에 실제로 돈을 넣는 투자자와 자산가입니다.

다음 기준으로 후보를 평가하세요.
- 투자 판단에 실제로 영향을 주는가 (수익률, 금리, 공실률, 거래량, 규제)
- 구체적인 숫자나 사실이 있는가
- 단순 인사·동정·행사 공지, 주거용 분양 홍보는 낮게 평가한다
- 상업용(오피스/리테일/물류/호텔)과 무관하면 낮게 평가한다

10점 만점으로 점수를 매기되 후하게 주지 마세요.
평범한 소식은 4~5점, 진짜 의미 있는 것만 7점 이상입니다."""

PROMPT = """오늘의 후보 목록입니다.

{candidates}

가장 가치 있는 것 하나를 고르고 JSON 으로만 답하세요.

{{
  "index": <후보 번호, 쓸 만한 게 하나도 없으면 -1>,
  "score": <0-10 정수>,
  "reason": "<투자자에게 왜 중요한지 2문장 이내. 기사 요약이 아니라 의미 해석>"
}}"""


def _format_candidates(articles: list[Article]) -> str:
    lines = []
    for i, a in enumerate(articles):
        when = a.published_at.astimezone(KST).strftime("%m-%d %H:%M") if a.published_at else "미상"
        lines.append(f"[{i}] ({a.source}, {when}) {a.title}\n    {a.snippet[:200]}")
    return "\n".join(lines)


def pick_fallback(path: str = "config/fallback.yaml") -> Pick:
    """요일로 백업 주제를 고른다. 같은 주에 같은 주제가 반복되지 않는다."""
    with open(path, encoding="utf-8") as f:
        topics = yaml.safe_load(f)["topics"]
    topic = topics[datetime.now(KST).weekday() % len(topics)]
    return Pick(
        article=None,
        score=0,
        reason="쓸 만한 신규 소스가 없어 백업 콘텐츠로 전환했습니다.",
        fallback_topic=f"{topic['label']}|{topic['prompt']}",
    )


def select(articles: list[Article], st: dict) -> Pick:
    seen = state_mod.seen_keys(st)
    previous = state_mod.recent_titles(st)

    fresh = [
        a for a in articles
        if a.key not in seen and not state_mod.is_near_duplicate(a.title, previous)
    ]
    print(f"[select] 후보 {len(articles)}건 → 중복 제거 후 {len(fresh)}건")

    if not fresh:
        return pick_fallback()

    result = ask_json(SYSTEM, PROMPT.format(candidates=_format_candidates(fresh)), effort="medium")
    idx = int(result.get("index", -1))
    score = int(result.get("score", 0))
    reason = str(result.get("reason", "")).strip()

    if idx < 0 or idx >= len(fresh) or score < SCORE_THRESHOLD:
        print(f"[select] 최고 점수 {score} < 임계값 {SCORE_THRESHOLD} → 백업 콘텐츠")
        return pick_fallback()

    chosen = fresh[idx]
    print(f"[select] 선정({score}점): {chosen.title[:60]}")
    return Pick(article=chosen, score=score, reason=reason)
