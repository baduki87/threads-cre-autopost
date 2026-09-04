"""초안 작성. config/voice.md 를 시스템 프롬프트로 주입한다.

핵심 규칙 하나: **의견은 메모에서만 나온다.**
메모가 없는 날 AI 가 전망을 지어내면 공인중개사 이름으로 가짜 판단이 나간다.
그래서 프롬프트를 메모용 / 뉴스용으로 나누고, 뉴스용은 opinion 을 비운다.
"""
from __future__ import annotations

from .llm import ask_json
from .models import Memo, Pick, Post

# 공통 출력 형식. opinion 만 분기별로 지시가 다르다.
_FIELDS = """{{
  "hook": "<제목 한 줄. 지역명+단지명 또는 사안. 40자 이내>",
  "body": "<관찰·사실. 한 줄에 하나씩, 줄바꿈으로 구분. 5~8줄. 개조식(~함/~다수/~용이)>",
  "opinion": {opinion_spec},
  "question": "<답하기 쉬운 질문 한 줄. 객관식이거나 한 단어로 답할 수 있어야 함>",
  "card_label": "<카드 상단 분류. 예: 임장 / 정책 / 재건축. 6자 이내>",
  "card_number": "<카드에 크게 박을 핵심 수치나 키워드. 예: 3천세대 / 사업시행인가. 없으면 빈 문자열>",
  "card_headline": "<카드 본문 문구. 30자 이내>",
  "source_line": {source_spec},
  "tags": []
}}

전체 500자를 넘기지 마세요. tags 는 항상 빈 배열입니다 — 이 계정은 해시태그를 쓰지 않습니다."""

MEMO_PROMPT = """아래는 작성자가 현장에서 직접 남긴 메모입니다.
이걸 스레드 게시물로 다듬으세요.

제목: {title}
메모:
{text}

지침:
- 메모에 있는 사실만 쓰세요. 없는 정보를 채워 넣지 마세요
- opinion 은 **메모에 담긴 작성자의 판단을 옮기는 것**입니다.
  메모에 판단이 없으면 opinion 을 빈 문자열로 두세요
- 전해 들은 내용은 "~라고 함" 으로 표시하세요

{spec}"""

NEWS_PROMPT = """아래 소재로 스레드 게시물을 작성하세요.

제목: {title}
출처: {source}
원문 링크: {url}
내용: {snippet}

편집장이 고른 이유: {reason}

지침:
- **opinion 은 반드시 빈 문자열로 두세요.** 작성자의 현장 메모가 없는 날입니다.
  전망이나 판단을 지어내면 안 됩니다
- 사실 전달 + 질문으로 끝냅니다
- 원문 표현을 그대로 옮기지 말고 사실만 가져와 새로 쓰세요

{spec}"""

FALLBACK_PROMPT = """오늘은 다룰 만한 신규 소재가 없습니다. 아래 주제로 작성하세요.

분류: {label}
주제: {topic}

지침:
- 시의성 있는 척하지 마세요. 최신 수치를 지어내지 마세요
- **opinion 은 빈 문자열로 두세요**
- 확실한 것만 쓰고, 질문으로 끝냅니다

{spec}"""

PERFORMANCE_BLOCK = """
## 지난 글의 실제 성과

잘 된 글:
{top}

반응이 없었던 글:
{bottom}

같은 계정, 같은 독자에게서 나온 결과입니다.
잘 된 쪽의 길이·구조·마무리를 따르세요.
"""


def _voice(path: str = "config/voice.md") -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _spec(*, allow_opinion: bool, with_source: bool) -> str:
    opinion_spec = (
        '"<메모에 담긴 작성자의 판단 한 줄. 개조식. 메모에 판단이 없으면 빈 문자열>"'
        if allow_opinion
        else '""'
    )
    source_spec = '"<출처 표기 한 줄>"' if with_source else '""'
    return _FIELDS.format(opinion_spec=opinion_spec, source_spec=source_spec)


def performance_context(state: dict, n: int = 5) -> str:
    """성과가 기록된 글이 쌓였을 때만 학습 블록을 만든다.

    조회수가 아직 안 채워진 초기에는 빈 문자열을 돌려주고 조용히 넘어간다.
    """
    scored = [
        p for p in state.get("posts", [])
        if isinstance(p.get("views"), int) and p.get("title")
    ]
    if len(scored) < 4:
        return ""

    def line(p: dict) -> str:
        return (
            f"- [{p.get('type') or p.get('kind', '?')}] {p['title'][:50]} "
            f"(조회 {p.get('views', 0)} / 좋아요 {p.get('likes', 0)} / 댓글 {p.get('replies', 0)})"
        )

    ranked = sorted(scored, key=lambda p: p.get("views", 0), reverse=True)
    top = "\n".join(line(p) for p in ranked[:n])
    bottom = "\n".join(line(p) for p in ranked[-n:][::-1])
    return PERFORMANCE_BLOCK.format(top=top, bottom=bottom)


def compose(pick: Pick, *, state: dict | None = None) -> Post:
    system = _voice()
    if state:
        system += performance_context(state)

    if pick.is_memo:
        m: Memo = pick.memo
        prompt = MEMO_PROMPT.format(
            title=m.title or "(제목 없음)",
            text=m.text,
            spec=_spec(allow_opinion=True, with_source=False),
        )
    elif pick.is_fallback:
        label, topic = (pick.fallback_topic or "관점|").split("|", 1)
        prompt = FALLBACK_PROMPT.format(
            label=label, topic=topic.strip(),
            spec=_spec(allow_opinion=False, with_source=False),
        )
    else:
        a = pick.article
        prompt = NEWS_PROMPT.format(
            title=a.title,
            source=a.source,
            url=a.url,
            snippet=a.snippet or "(요약 없음 — 제목만으로 판단하세요)",
            reason=pick.reason,
            spec=_spec(allow_opinion=False, with_source=True),
        )

    d = ask_json(system, prompt, effort="high")

    opinion = str(d.get("opinion", "")).strip()
    if not pick.is_memo and opinion:
        # 안전장치: 메모가 없는데 판단이 나왔으면 버린다.
        print("[compose] 메모 없는 날 opinion 이 생성되어 제거했습니다.")
        opinion = ""

    post = Post(
        hook=str(d.get("hook", "")).strip(),
        body=str(d.get("body", "")).strip(),
        opinion=opinion,
        question=str(d.get("question", "")).strip(),
        card_label=str(d.get("card_label", "")).strip()[:6],
        card_number=str(d.get("card_number", "")).strip(),
        card_headline=str(d.get("card_headline", "")).strip(),
        source_line=str(d.get("source_line", "")).strip(),
        tags=[],   # 이 계정은 해시태그를 쓰지 않는다
    )

    text = post.render_text()
    print(
        f"[compose] 본문 {len(text)}자 / 의견 {'있음' if post.opinion else '없음'}"
        f" / 질문 {'있음' if post.question else '없음'}"
    )
    return post
