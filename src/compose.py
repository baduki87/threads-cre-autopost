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
{series}

지침:
- 시의성 있는 척하지 마세요. 최신 수치를 지어내지 마세요
- **opinion 은 빈 문자열로 두세요**
- **바로 따라 할 수 있게 쓰세요.** 순서가 있으면 번호를 붙입니다
- **제목에 개수를 쓰려면 본문 항목 수와 반드시 맞추세요.**
  "4단계" 라고 써놓고 다섯 개를 나열하면 안 됩니다.
  헷갈리면 제목에 개수를 넣지 마세요
- 질문으로 끝내지 마세요. 정리로 끝냅니다

{spec}"""

SERIES_1 = """
**이 글은 2편 중 1편입니다.**
- 주제의 **앞부분 절반만** 다루세요. 다 쏟지 마세요
- 본문 마지막 줄에 다음 편 예고를 넣으세요.
  예: "나머지 절반은 다음 글에서 이어서 정리하겠습니다."
- detail(첫 댓글)은 1편 내용의 보충입니다. 2편 내용을 미리 쓰지 마세요"""

SERIES_2 = """
**이 글은 2편 중 2편입니다.**
- 1편에서 앞부분을 이미 다뤘습니다. **나머지 절반**을 쓰세요
- 첫 줄에 이어지는 글임을 밝히세요. 예: "지난 글에 이어서 정리합니다."
- 예고는 넣지 마세요. 여기서 마무리합니다"""

QUESTION_PROMPT = """독자에게 던지는 **질문 글**을 작성하세요.
이 계정에서 댓글이 가장 많이 달리는 유형입니다.

## 읽는 사람이 둘입니다

  집을 사려는 사람  — "저도 그때 그랬어요" 로 답합니다
  동종 공인중개사    — "저희는 이렇게 합니다" 로 답합니다

**양쪽이 각자 자기 입장에서 답할 수 있게 쓰세요.** 실측으로 가장 잘 된 질문
("중개사무소에서 질문이 막히는 순간", 조회 651·좋아요 8·댓글 2)에 답을 단
두 사람이 모두 중개사였습니다.

"A와 B 중 무엇이 더 좋은가" 는 쓰지 마세요. 그렇게 낸 두 건이 연속으로
좋아요 0 이었습니다. **현장의 구체적인 상황**을 집어내야 합니다.

주제: {label}
무엇을 물을지: {topic}

## 이번 글의 모양: {shape_name}

{shape_rule}

{title_rule}

지침:
- **배경은 한두 줄이면 충분합니다.** 길게 설명하면 질문이 죽습니다
- **계정 주인은 답을 내놓지 않습니다.** 묻기만 합니다.
  opinion 은 반드시 빈 문자열입니다
- question 이 이 글의 전부입니다. 읽자마자 한 줄로 답할 수 있어야 합니다
- 특정인에게 하는 투자 권유로 읽히지 않게, 일반적인 상황으로 물으세요
- **금액과 특정 지역·단지를 함께 묶지 마세요.** 이게 가장 중요합니다.
  "현금 10억이면 강남 재건축과 마용성 신축 중 어디" 라고 물었다가
  "10억에 그게 가능한가요?" 라는 지적을 받았습니다. 둘 다 10억으로 못 삽니다.
  공인중개사 계정이 시세를 틀리면 그 한 줄로 신뢰가 무너집니다.
  금액을 모르면 쓰지 마세요. **구체성은 금액이 아니라 상황에서 만듭니다.**
    나쁨: 현금 10억이 생긴다면 강남 재건축과 마용성 신축 중 어디를
    좋음: 전세 만기가 왔을 때 갱신과 매수 중 어느 쪽을
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


# 질문 글의 모양. 코드가 돌려가며 고른다.
#
# 09-23 이후 질문 글 11건이 전부 같은 틀이었다.
#   "~라고들 합니다" → "~라는 말이 많습니다" → "A입니까, B입니까?"
# 제목 절반이 "~순간". 조회는 올랐지만(중앙값 193 → 293) 진짜 댓글은
# 13건에 7개 → 11건에 2개로 줄었고, 09-30 이후 7건은 0이었다.
# 처음 6건이 같은 틀이라 기계로 읽혔던 실패를 그대로 반복한 것이다.
# 프롬프트에 "다양하게" 라고 써서는 안 바뀐다. 모양을 코드가 정해서 넘긴다.
QUESTION_SHAPES: dict[str, str] = {
    "하나만": """**딱 하나만** 꼽아달라고 묻습니다. 답이 한 단어나 짧은 한 줄로 끝나야 합니다.
  예: "계약서 볼 때 제일 먼저 확인하는 항목, 하나만 꼽는다면요?"
- 보기를 주지 마세요. 독자가 자기 답을 직접 씁니다
- "~라고들 합니다" 같은 통념 문장은 쓰지 마세요""",
    "경험": """독자가 **실제로 겪은 일**을 꺼내게 묻습니다. "그런 적 있으신가요? 뭐 때문이었나요" 형태입니다.
- 배경 없이 질문으로 바로 들어가도 됩니다. body 는 한 줄이면 충분합니다
- 보기 둘을 나열하지 마세요
- "~라고들 합니다" 같은 통념 문장은 쓰지 마세요""",
    "통념확인": """떠도는 통념 한 줄을 놓고 **맞는지 틀린지**만 묻습니다. "맞다/아니다" 로 답하게 합니다.
  예: "1주택 실거주하면서 자산을 쌓아야 상급지로 갈 수 있다고들 하죠. 정말 그런가요?"
- 통념은 반드시 "~라고들 합니다/하죠" 처럼 **남의 말**로 씁니다. 계정 주인의 판단으로 쓰면 안 됩니다
- 보기 둘을 나열하지 마세요. 질문은 예/아니오로 답할 수 있어야 합니다""",
    "택일": """둘 중 하나를 고르게 묻습니다. 보기 둘은 **실제 상황의 선택지**여야 합니다.
  좋음: 전세 만기가 왔을 때 갱신과 매수 중 어느 쪽을
  나쁨: 대단지와 소단지 중 무엇이 더 좋은가
- 배경은 상황 설명 한 줄. "~라고들 합니다" 같은 통념 문장은 쓰지 마세요""",
}
# 이전 기록에는 모양이 없다. 그때는 전부 택일이었다.
_DEFAULT_SHAPE = "택일"
_HEARSAY = ("고들 ", "말이 많", "라고 합니다", "다고 합니다")


def _recent_questions(state: dict | None, n: int = 3) -> list[dict]:
    posts = [p for p in (state or {}).get("posts", [])
             if p.get("type") == "질문" and not p.get("dry_run")]
    return posts[-n:]


def pick_shape(state: dict | None) -> str:
    """최근 질문 글에 쓴 모양을 피해서 고른다. 순서는 정의 순서.

    댓글이 끊긴 쪽이 택일·통념이라 그 둘을 뒤에 뒀다.
    """
    used = [p.get("shape") or _DEFAULT_SHAPE for p in _recent_questions(state)]
    for name in QUESTION_SHAPES:
        if name not in used:
            return name
    # 다 썼으면 가장 오래 전에 쓴 것
    return min(QUESTION_SHAPES, key=lambda k: max(
        (i for i, u in enumerate(used) if u == k), default=-1))


def _hook_of(title: str) -> str:
    # 기록의 제목은 "[라벨] 제목" 모양이다
    return title.split("] ", 1)[-1].strip()


def _last_word(text: str) -> str:
    words = text.strip().rstrip(".?!…~ ").split()
    return words[-1] if words else ""


def banned_endings(state: dict | None, n: int = 5) -> set[str]:
    """최근 질문 글 제목의 마지막 낱말. 같은 말로 끝나는 제목을 막는다."""
    out = {_last_word(_hook_of(p.get("title", ""))) for p in _recent_questions(state, n)}
    out.discard("")
    return out


def question_problems(d: dict, shape: str, banned: set[str]) -> list[str]:
    """질문 글이 틀을 반복하는지 코드로 검사한다. 빈 목록이면 통과."""
    problems = []
    hook = str(d.get("hook", "")).strip()
    if _last_word(hook) in banned or any(hook.rstrip(".?!…~ ").endswith(b) for b in banned):
        problems.append(f"제목이 최근 글과 같은 말로 끝남: {hook}")
    if "순간" in hook and "순간" in banned:
        problems.append(f"제목에 '순간' 이 또 들어감: {hook}")
    if shape != "통념확인":
        text = str(d.get("body", "")) + str(d.get("question", ""))
        if any(h in text for h in _HEARSAY):
            problems.append("통념 문장('~라고들 합니다')을 또 씀")
    if not str(d.get("question", "")).strip():
        problems.append("질문이 비어 있음")
    return problems


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

    want_question = False
    shape = ""

    if pick.is_memo:
        m: Memo = pick.memo
        want_question = True
        prompt = MEMO_PROMPT.format(
            title=m.title or "(제목 없음)",
            text=m.text,
            # 임장기는 계정 주인이 원래 쓰던 평서체로 쓴다. 가장 잘 된 글들이 그 말투다.
            spec=_spec(allow_opinion=True, tone=TONE_PLAIN, lines="3~8",
                       want_question=True,
                       detail_from="메모에 있지만 본문에 못 담은 현장 정보를 옮깁니다."),
        )
    elif pick.is_question:
        want_question = True
        label, topic = (pick.question_topic or "질문|").split("|", 1)
        shape = pick_shape(state)
        banned = banned_endings(state)
        prompt = QUESTION_PROMPT.format(
            label=label, topic=topic.strip(),
            shape_name=shape, shape_rule=QUESTION_SHAPES[shape],
            title_rule=(
                "제목은 다음 말로 끝내지 마세요(최근 질문 글이 이렇게 끝났습니다): "
                + ", ".join(sorted(banned)) if banned else ""),
            spec=_spec(allow_opinion=False, lines="1~3", want_question=True,
                       detail_from="질문 글에는 첫 댓글을 달지 않습니다. 빈 문자열입니다."),
        )
    elif pick.is_fallback:
        label, topic = (pick.fallback_topic or "관점|").split("|", 1)
        prompt = FALLBACK_PROMPT.format(
            label=label, topic=topic.strip(),
            series={1: SERIES_1, 2: SERIES_2}.get(pick.part, ""),
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

    if pick.is_question:
        # 프롬프트로 부탁만 하면 같은 틀로 돌아간다. 걸리면 이유를 붙여 다시 쓰게 한다.
        for _ in range(2):
            problems = question_problems(d, shape, banned)
            if not problems:
                break
            print(f"[compose] 질문 글 다시 생성: {' / '.join(problems)}")
            d = ask_json(system, prompt + "\n\n## 방금 쓴 글의 문제\n"
                         + "\n".join(f"- {x}" for x in problems)
                         + "\n위 문제를 고쳐서 다시 쓰세요.", effort="high")
        else:
            problems = question_problems(d, shape, banned)
            if problems:
                print(f"[compose] 두 번 고쳐도 남은 문제(그대로 씁니다): {' / '.join(problems)}")

    opinion = str(d.get("opinion", "")).strip()
    if not pick.is_memo and opinion:
        # 안전장치: 메모가 없는데 판단이 나왔으면 버린다.
        print("[compose] 메모 없는 날 opinion 이 생성되어 제거했습니다.")
        opinion = ""

    if not want_question and str(d.get("question", "")).strip():
        # 안전장치: 프롬프트로 "질문을 쓰지 마세요" 라고만 해서는 안 막혔다.
        # 방법론 글이 "주차와 경사 중 어느 쪽을 먼저 보시나요?" 로 끝나버렸고,
        # 그게 바로 없애려던 그 AI 티였다(6건 연속 질문 마무리). 코드로 막는다.
        print("[compose] 질문을 쓰지 않는 유형인데 생성되어 제거했습니다.")
        d["question"] = ""

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
        shape=shape if pick.is_question else "",
    )

    text = post.render_text()
    detail = post.render_detail()
    print(
        f"[compose] 본문 {len(text)}자 / 의견 {'있음' if post.opinion else '없음'}"
        f" / 질문 {'있음' if post.question else '없음'}"
        f" / 첫 댓글 {f'{len(detail)}자' if detail else '없음'}"
    )
    return post
