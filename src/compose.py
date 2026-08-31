"""요약 + 카피 생성. config/voice.md 를 시스템 프롬프트로 주입한다."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .llm import ask_json
from .models import Pick, Post

KST = timezone(timedelta(hours=9))

OUTPUT_SPEC = """JSON 객체 하나로만 답하세요.

{
  "hook": "<첫 줄. 40자 이내>",
  "body": "<본문. 2~4문장>",
  "takeaway": "<그래서 투자자에게 무슨 의미인지 한 줄>",
  "card_label": "<카드 상단 분류. 예: 오피스 / 물류 / 정책 / 리테일. 6자 이내>",
  "card_number": "<카드에 크게 박을 핵심 수치. 예: 2.4% / 1.2조원 / 3분기 연속. 없으면 빈 문자열>",
  "card_headline": "<카드 본문 문구. 30자 이내>",
  "source_line": "<출처 표기 한 줄>",
  "tags": ["<해시태그 2~3개, # 없이>"]
}

hook + body + takeaway + source_line + 태그를 합쳐 500자를 넘기지 마세요."""

NEWS_PROMPT = """아래 소재로 스레드 게시물을 작성하세요.

제목: {title}
출처: {source}
원문 링크: {url}
내용: {snippet}

편집장이 이 소재를 고른 이유:
{reason}

이 "고른 이유"를 takeaway 의 출발점으로 삼되, 그대로 옮기지 말고 독자에게 하는 말로 다시 쓰세요.

{spec}"""

FALLBACK_PROMPT = """오늘은 다룰 만한 신규 뉴스가 없습니다. 아래 주제로 게시물을 작성하세요.

분류: {label}
주제: {topic}

시의성 있는 척하지 마세요. 최신 수치를 지어내지 말고, 확실한 것만 쓰세요.

{spec}"""


def _voice(path: str = "config/voice.md") -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def compose(pick: Pick) -> Post:
    system = _voice()

    if pick.is_fallback:
        label, topic = (pick.fallback_topic or "관점|").split("|", 1)
        prompt = FALLBACK_PROMPT.format(label=label, topic=topic.strip(), spec=OUTPUT_SPEC)
    else:
        a = pick.article
        prompt = NEWS_PROMPT.format(
            title=a.title,
            source=a.source,
            url=a.url,
            snippet=a.snippet or "(요약 없음 — 제목만으로 판단하세요)",
            reason=pick.reason,
            spec=OUTPUT_SPEC,
        )

    d = ask_json(system, prompt, effort="high")

    post = Post(
        hook=str(d.get("hook", "")).strip(),
        body=str(d.get("body", "")).strip(),
        takeaway=str(d.get("takeaway", "")).strip(),
        card_label=str(d.get("card_label", "")).strip()[:6],
        card_number=str(d.get("card_number", "")).strip(),
        card_headline=str(d.get("card_headline", "")).strip(),
        source_line=str(d.get("source_line", "")).strip(),
        tags=[str(t).strip() for t in (d.get("tags") or []) if str(t).strip()][:3],
    )

    text = post.render_text()
    print(f"[compose] 본문 {len(text)}자 / 카드 '{post.card_number}' '{post.card_headline}'")
    return post
