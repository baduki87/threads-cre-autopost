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
  "hook": "<제목 한 줄. 40자 이내. {tone_hint}>",
  "body": "<본문. **{lines}줄**. 줄바꿈으로 구분. {tone_hint}>",
  "opinion": {opinion_spec},
  "question": {question_spec},
  "detail": {detail_spec},
  "card_label": "<카드 상단 분류. 예: 임장 / 정책 / 재건축. 6자 이내>",
  "card_number": "<카드에 크게 박을 핵심 수치나 키워드. 없으면 빈 문자열>",
  "card_headline": "<카드 본문 문구. 30자 이내>",
  "source_line": "",
  "tags": []
}}

지켜야 할 것:
- **'~인 것 같습니다', '~인 듯합니다', '~로 보여집니다' 는 절대 쓰지 마세요.** 힘이 빠집니다
- **출처를 쓰지 마세요.** source_line 은 항상 빈 문자열입니다.
  반응 좋은 계정 중 출처를 붙이는 곳이 하나도 없습니다
- 제목을 매번 '~습니다' 로 끝내지 마세요. 명사로 끊거나 수치로 시작해도 됩니다
- tags 는 항상 빈 배열입니다 — 이 계정은 해시태그를 쓰지 않습니다"""

MEMO_PROMPT = """아래는 작성자가 현장에서 직접 남긴 메모입니다.
이걸 스레드 게시물로 다듬으세요.

제목: {title}
메모:
{text}

지침:
- 메모에 있는 사실만 쓰세요. 없는 정보를 채워 넣지 마세요
- opinion 은 **메모에 담긴 작성자의 판단을 옮기는 것**입니다.
  메모에 판단이 없으면 opinion 을 빈 문자열로 두세요
- 전해 들은 내용은 "~라고 합니다" 로 표시하세요
- **계정 주인의 원래 말투(평서체)로 쓰세요.** 존댓말로 고치면 남의 글이 됩니다
- 메모 내용이 많으면 중요한 것만 body 에 넣고 나머지는 detail 로 보내세요

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
- 원문 표현을 그대로 옮기지 말고 사실만 가져와 새로 쓰세요
- **질문으로 끝내지 마세요.** 사실만 전하고 끝냅니다.
  요약 뒤에 습관처럼 붙는 질문은 댓글을 만들지 못했습니다

{spec}"""

FALLBACK_PROMPT = """아래 주제로 방법론 글을 작성하세요.

분류: {label}
주제: {topic}

지침:
- 시의성 있는 척하지 마세요. 최신 수치를 지어내지 마세요
- **opinion 은 빈 문자열로 두세요**
- **바로 따라 할 수 있게 쓰세요.** 순서가 있으면 번호를 붙입니다
- **제목에 개수를 쓰려면 본문 항목 수와 반드시 맞추세요.**
  "4단계" 라고 써놓고 다섯 개를 나열하면 안 됩니다.
  헷갈리면 제목에 개수를 넣지 마세요
- 질문으로 끝내지 마세요. 정리로 끝냅니다

{spec}"""

QUESTION_PROMPT = """독자에게 던지는 **질문 글**을 작성하세요.
이 계정에서 댓글이 가장 많이 달리는 유형입니다.

주제: {label}
무엇을 물을지: {topic}

지침:
- **배경은 한두 줄이면 충분합니다.** 길게 설명하면 질문이 죽습니다
- **계정 주인은 답을 내놓지 않습니다.** 묻기만 합니다.
  opinion 은 반드시 빈 문자열입니다
- question 이 이 글의 전부입니다. 둘 중 하나를 고르게 하세요
- 특정인에게 하는 투자 권유로 읽히지 않게, 일반적인 상황으로 물으세요
- 최신 수치나 시세를 지어내지 마세요
- detail 은 빈 문자열로 두세요. 질문 글에 첫 댓글을 달면 답을 유도하게 됩니다

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


# 평서체는 계정 주인이 원래 쓰던 말투다. 존댓말로 고치면 남의 글이 된다.
TONE_PLAIN = "평서체입니다 ('~다', '~군', '~음'). 명사로 끝내도 됩니다"
TONE_POLITE = "존댓말 '~합니다' 단정형입니다"


def _spec(*, allow_opinion: bool, detail_from: str, tone: str = TONE_POLITE,
          lines: str = "2~6", want_question: bool = True) -> str:
    """소재 종류마다 문체·길이·질문 여부가 달라야 한다.

    전부 같은 값으로 6건을 냈더니 기계로 읽혔다. 그래서 인자로 뺐다.
    """
    opinion_spec = (
        '"<메모에 담긴 작성자의 판단 한 줄. 메모에 판단이 없으면 빈 문자열>"'
        if allow_opinion
        else '""'
    )
    question_spec = (
        '"<답하기 쉬운 질문 한 줄. 둘 중 택일이거나 한 단어로 답할 수 있어야 함>"'
        if want_question
        else '"<빈 문자열. 이번 글은 질문으로 끝내지 않습니다>"'
    )
    detail_spec = (
        f'"<첫 댓글에 붙일 상세. {detail_from} '
        '본문과 중복되지 않게 씁니다. 500자 이내. 없으면 빈 문자열>"'
    )
    return _FIELDS.format(opinion_spec=opinion_spec, question_spec=question_spec,
                          detail_spec=detail_spec, tone_hint=tone, lines=lines)


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
        slot = f"{p['slot']}시 " if p.get("slot") else ""
        return (
            f"- {slot}[{p.get('type') or p.get('kind', '?')}] {p['title'][:50]} "
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
            # 임장기는 계정 주인이 원래 쓰던 평서체로 쓴다. 가장 잘 된 글들이 그 말투다.
            spec=_spec(allow_opinion=True, tone=TONE_PLAIN, lines="3~8",
                       want_question=True,
                       detail_from="메모에 있지만 본문에 못 담은 현장 정보를 옮깁니다."),
        )
    elif pick.is_question:
        label, topic = (pick.question_topic or "질문|").split("|", 1)
        prompt = QUESTION_PROMPT.format(
            label=label, topic=topic.strip(),
            spec=_spec(allow_opinion=False, lines="1~3", want_question=True,
                       detail_from="질문 글에는 첫 댓글을 달지 않습니다. 빈 문자열입니다."),
        )
    elif pick.is_fallback:
        label, topic = (pick.fallback_topic or "관점|").split("|", 1)
        prompt = FALLBACK_PROMPT.format(
            label=label, topic=topic.strip(),
            spec=_spec(allow_opinion=False, lines="4~8", want_question=False,
                       detail_from="본문에서 다 못 쓴 배경이나 구체적인 방법을 덧붙입니다."),
        )
    else:
        a = pick.article
        prompt = NEWS_PROMPT.format(
            title=a.title,
            source=a.source,
            url=a.url,
            snippet=a.snippet or "(요약 없음 — 제목만으로 판단하세요)",
            reason=pick.reason,
            spec=_spec(allow_opinion=False, lines="2~5", want_question=False,
                       detail_from="기사에 있는 구체적 조건·일정·적용 범위를 정리합니다."),
        )

    d = ask_json(system, prompt, effort="high")

    opinion = str(d.get("opinion", "")).strip()
    if not pick.is_memo and opinion:
        # 안전장치: 메모가 없는데 판단이 나왔으면 버린다.
        print("[compose] 메모 없는 날 opinion 이 생성되어 제거했습니다.")
        opinion = ""

    if pick.is_question:
        # 질문 글에 첫 댓글을 달면 계정 주인이 답을 유도하는 모양이 된다.
        d["detail"] = ""

    post = Post(
        hook=str(d.get("hook", "")).strip(),
        body=str(d.get("body", "")).strip(),
        opinion=opinion,
        question=str(d.get("question", "")).strip(),
        detail=str(d.get("detail", "")).strip(),
        card_label=str(d.get("card_label", "")).strip()[:6],
        card_number=str(d.get("card_number", "")).strip(),
        card_headline=str(d.get("card_headline", "")).strip(),
        source_line=str(d.get("source_line", "")).strip(),
        tags=[],   # 이 계정은 해시태그를 쓰지 않는다
    )

    text = post.render_text()
    detail = post.render_detail()
    print(
        f"[compose] 본문 {len(text)}자 / 의견 {'있음' if post.opinion else '없음'}"
        f" / 질문 {'있음' if post.question else '없음'}"
        f" / 첫 댓글 {f'{len(detail)}자' if detail else '없음'}"
    )
    return post
