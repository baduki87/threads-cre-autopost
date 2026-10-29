"""후보 선별: 중복 제거 → AI 스코어링 → 임계값 미달 시 백업 콘텐츠 전환.

메모가 있는 날은 이 단계를 건너뛴다 (draft.py 에서 처리).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import yaml

from . import state as state_mod
from . import subjects as subj
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
                  st: dict | None = None, category: str = "") -> Pick:
    """백업 주제 하나. 최근에 쓴 주제를 피한다.

    예전에는 요일로 골랐는데 주제가 5개뿐이라 매주 같은 요일에 같은 주제가
    돌아왔다. 하루 3건이면 이틀에 한 바퀴라 더 빨리 뻔해진다.

    최근 제목에서 주제를 알아보려면 이력에 label 이 남아 있어야 한다.
    main._source_id 가 백업 글을 "[임장준비] ..." 형태로 기록하는 이유다.
    """
    with open(path, encoding="utf-8") as f:
        topics = yaml.safe_load(f)["topics"]
    if category:
        # 21시 슬롯은 AI 주제만 쓴다. 해당 분류가 비어 있으면 전체에서 고른다.
        topics = [t for t in topics if t.get("category") == category] or topics

    recent = set()
    if st:
        # 최근 발행 제목에 들어간 분류를 훑어 같은 주제를 연달아 쓰지 않는다.
        recent = {t for t in state_mod.recent_titles(st, days=10)}

    unseen = [t for t in topics if not any(t["label"] in r for r in recent)]

    # 같은 묶음(group)을 최근 7일 안에 다뤘으면 피한다. 라벨만 피했더니
    # 임대차 현황표·AI 렌트롤·임차인 승계가 번갈아 나와 2주에 렌트롤 이야기가 5번이었다(10-22).
    used_groups: set = set()
    with open(path, encoding="utf-8") as f:
        every = yaml.safe_load(f)["topics"]   # 분류(실무·AI)를 넘어 묶음을 본다
    if st:
        week = state_mod.recent_titles(st, days=7)
        used_groups = {t.get("group") for t in every
                       if t.get("group") and any(f"[{t['label']}]" in r for r in week)}

    # 종류(방법론·질문·AI)를 넘어 최근 10일 제목에 나온 소재도 피한다(10-29).
    hot = subj.recent_subjects(st)
    fresh = [t for t in unseen if t.get("group") not in used_groups
             and not (subj.topic_subjects(t) & hot)]
    if fresh:
        topic = fresh[datetime.now(KST).timetuple().tm_yday % len(fresh)]
    else:
        # 새 주제가 없으면 **묶음 기준으로 가장 오래전에 다룬 것**부터, 같으면 주제 기준으로.
        # 날짜로 아무거나 고르면 어제 쓴 주제가 또 나오거나(10-22 시험: AI 안내문 이틀 연속)
        # 같은 묶음이 사흘 연속 나왔다(수익률 → AI 수익률표 → 대출 점검).
        def _group_last(t):
            labels = [x["label"] for x in every if x.get("group") == t.get("group")] or [t["label"]]
            return max(_last_used(st, l) for l in labels)
        topic = min(topics, key=lambda t: (bool(subj.topic_subjects(t) & hot),
                                           _group_last(t), _last_used(st, t["label"])))

    return Pick(
        article=None,
        score=0,
        reason="쓸 만한 신규 소스가 없어 백업 콘텐츠로 전환했습니다.",
        fallback_topic=f"{topic['label']}|{topic['prompt']}",
    )


def _last_used(st: dict | None, label: str) -> str:
    """그 주제를 마지막으로 쓴 날짜(ISO 문자열). 안 썼으면 빈 문자열 → 가장 먼저 고른다."""
    dates = [p.get("date", "") for p in (st or {}).get("posts", [])
             if f"[{label}]" in p.get("title", "")]
    return max(dates) if dates else ""


def fallback_by_label(label: str, path: str = "config/fallback.yaml") -> Pick | None:
    """연재 2편을 쓰려고 1편과 같은 주제를 다시 집어온다."""
    with open(path, encoding="utf-8") as f:
        topics = yaml.safe_load(f)["topics"]
    for t in topics:
        if t["label"] == label:
            return Pick(article=None, score=0, reason="연재 2편입니다.",
                        fallback_topic=f"{t['label']}|{t['prompt']}", part=2)
    return None


def pick_question(path: str = "config/questions.yaml",
                  st: dict | None = None) -> Pick:
    """질문 글 주제 하나. 최근에 쓴 주제를 피한다.

    이 계정에서 댓글이 가장 많이 달리는 유형이고, **판단을 쓰지 않아도 되므로**
    자동화와 충돌하지 않는다. AI 는 묻기만 하고 답은 독자가 한다.
    """
    with open(path, encoding="utf-8") as f:
        topics = yaml.safe_load(f)["topics"]

    recent = set()
    if st:
        recent = {t for t in state_mod.recent_titles(st, days=21)}
    unseen = [t for t in topics if not any(t["label"] in r for r in recent)]
    hot = subj.recent_subjects(st)
    cool = [t for t in unseen if not (subj.topic_subjects(t) & hot)]
    pool = cool or unseen or topics
    topic = pool[datetime.now(KST).timetuple().tm_yday % len(pool)]

    return Pick(
        article=None,
        score=0,
        reason="질문 글 슬롯입니다.",
        question_topic=f"{topic['label']}|{topic['prompt']}",
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
