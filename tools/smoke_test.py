"""LLM 호출만 스텁으로 대체하고 파이프라인 전체를 실제로 돌린다.

API 키 없이 수집 → 선별 → 조립 → 카드 렌더링 → 본문 길이까지 검증한다.
사용법:  python tools/smoke_test.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import compose as compose_mod
from src import llm, select as select_mod
from src.models import Post

CALLS: list[str] = []


def fake_ask_json(system: str, prompt: str, **kwargs) -> dict:
    """select 용 / compose 용 응답을 프롬프트로 구분해 돌려준다."""
    if '"index"' in prompt:
        CALLS.append("select")
        return {"index": 0, "score": 8, "reason": "테스트용 선별 사유입니다."}
    CALLS.append("compose")
    return {
        "hook": "1주택자 갈아타기 대출 규제가 바뀝니다",
        # 4줄을 일부러 넣는다 — 3줄 강제가 작동하는지 보는 회귀 테스트
        "body": ("수도권 주택담보대출 한도가 조정됩니다.\n"
                 "실행일 기준으로 적용됩니다.\n"
                 "기존 계약분은 종전 기준이 유지됩니다.\n"
                 "이 네 번째 줄은 잘려야 합니다."),
        # 메모가 없는 날이라 의견을 넣어봤지만 compose 가 걸러내야 한다 (안전장치 회귀 테스트)
        "opinion": "지금이 매수 기회로 봅니다",
        "question": "이번 규제로 계획이 바뀌신 분 계신가요?",
        "detail": "적용 대상과 예외 조항을 정리합니다. 생애최초 구입자는 종전 한도가 유지됩니다.",
        "card_label": "정책",
        "card_number": "주담대",
        "card_headline": "1주택자 갈아타기 대출 한도 조정",
        "source_line": "출처: 국토교통부",
        "tags": [],
    }


llm.ask_json = fake_ask_json
select_mod.ask_json = fake_ask_json
compose_mod.ask_json = fake_ask_json

os.environ["DRY_RUN"] = "1"
os.environ.setdefault("THREADS_ACCOUNT_HANDLE", "@pro_konwoo")

from src.main import run  # noqa: E402  (스텁 주입 후에 임포트해야 한다)

code = run()

print(f"\nLLM 호출 순서: {CALLS}")

# 500자 제한 회귀 테스트 — 과하게 긴 응답도 잘려야 한다
long_post = Post(
    hook="가" * 100,
    body="나" * 300,
    opinion="다" * 120,
    question="라" * 80,
    detail="마" * 700,
    card_label="테스트",
    card_number="1",
    card_headline="테스트",
    source_line="출처: 테스트",
    tags=["가", "나", "다"],
)
rendered = long_post.render_text()
assert len(rendered) <= 500, f"500자 제한 위반: {len(rendered)}자"
assert "라" * 80 in rendered, "질문은 잘리지 않고 끝까지 남아야 한다"
print(f"길이 제한 테스트 통과: {len(rendered)}자 (질문 보존 확인)")

# 메모 기반 글은 의견이 살아있어야 한다
from src.models import Memo, Pick  # noqa: E402
memo_pick = Pick(article=None, score=0, reason="",
                 memo=Memo(page_id="x", title="은마 임장", text="재건축 속도 빠름"))
assert memo_pick.is_memo and not memo_pick.is_fallback, "메모 판정 오류"
print("메모 판정 테스트 통과")

# 본문과 첫 댓글은 섞이면 안 된다
assert "마" * 50 not in rendered, "첫 댓글이 본문에 섞였다"
d = long_post.render_detail()
assert len(d) <= 500 and d.endswith("…"), f"첫 댓글 길이 제한 실패: {len(d)}자"
print(f"첫 댓글 분리·제한 통과: {len(d)}자")

# 줄 수는 이제 고정하지 않는다. 상한만 막힌다.
from src.models import BODY_MAX_LINES  # noqa: E402
short = Post(hook="h", body="1\n2")
assert short.body == "1\n2", f"짧은 본문을 건드리면 안 된다: {short.body!r}"
long_body = Post(hook="h", body="\n".join(str(i) for i in range(BODY_MAX_LINES + 5)))
assert long_body.body.count("\n") == BODY_MAX_LINES - 1, long_body.body
assert Post(hook="h", body="한 줄").body == "한 줄"
print(f"본문 줄 수 자유 통과 (상한 {BODY_MAX_LINES}줄만 강제)")


# 슬롯 사이 중복 회귀 테스트
#   08시에 발행한 기사가 17시에 다시 뽑히면 안 된다. 그러려면 이력에 남는 키와
#   제목이 AI 가 다시 쓴 것이 아니라 **원본 기사**의 것이어야 한다.
from datetime import datetime, timezone, timedelta  # noqa: E402
from src import state as state_mod  # noqa: E402
from src.main import _source_id  # noqa: E402
from src.models import Article  # noqa: E402

원본 = Article(title="용적률 1.2배 높이면 성산시영 분담금 1억 뚝",
               url="https://example.com/news/1", source="매일경제", kind="news")
아침글 = Post(hook="마포 성산시영 용적률 완화 시뮬레이션 결과가 나왔습니다",
              body="1\n2\n3", card_label="", card_number="",
              card_headline="", source_line="")

key, title = _source_id(Pick(article=원본, score=8, reason=""), 아침글, "2026-09-06", "08")
assert key == 원본.key, f"기사 키가 아니라 {key} 가 기록됐다"
assert title == 원본.title, f"AI 제목이 기록됐다: {title}"

st = state_mod.record({}, key=key, title=title, url=원본.url, post_id="1",
                      kind="auto", type_="뉴스", slot="08", dry_run=False)

# 같은 기사 → 키로 걸린다
같은기사 = Article(title=원본.title, url=원본.url, source="매일경제", kind="news")
# 같은 사건, 다른 매체 → 제목 겹침으로 걸린다
다른매체 = Article(title="성산시영 용적률 완화, 분담금 1억 줄어",
                  url="https://example.com/news/2", source="뉴시스", kind="news")
무관 = Article(title="강남 재건축 조합 설립 인가 신청",
              url="https://example.com/news/3", source="조선비즈", kind="news")

seen = state_mod.seen_keys(st)
prev = state_mod.recent_titles(st)
통과 = [a for a in (같은기사, 다른매체, 무관)
        if a.key not in seen and not state_mod.is_near_duplicate(a.title, prev)]
assert [a.title for a in 통과] == [무관.title], [a.title for a in 통과]
print("슬롯 사이 중복 차단 통과: 같은 기사·같은 사건 제외, 무관 기사 통과")

# 백업 주제는 label 을 제목에 남겨야 다음 슬롯이 회전할 수 있다
fb_key, fb_title = _source_id(
    Pick(article=None, score=0, reason="", fallback_topic="임장준비|..."),
    아침글, "2026-09-06", "08")
assert fb_title.startswith("[임장준비]"), fb_title
print("백업 주제 회전 근거 기록 통과")


# 댓글 분류의 안전장치
#   자동 답글의 기본값은 '안 함' 이어야 한다. AI 응답이 어떻게 망가지든
#   상담·부정으로 새면 사람에게 가고, 답글은 비어야 한다.
from src import replies as replies_mod  # noqa: E402

def 분류시험(응답: dict) -> dict:
    replies_mod.ask_json = lambda *a, **k: 응답
    return replies_mod.classify({"username": "t", "text": "아무거나"}, "원글")

r = 분류시험({"kind": "상담", "reply": "지금이 매수 기회입니다", "why": ""})
assert r["kind"] == "상담" and r["reply"] == "", r
r = 분류시험({"kind": "부정", "reply": "그건 틀렸습니다", "why": ""})
assert r["reply"] == "", r
r = 분류시험({"kind": "사실질문", "reply": "", "why": "근거 없음"})
assert r["kind"] == "상담", f"근거 없는 사실질문은 사람에게 가야 한다: {r}"
r = 분류시험({"kind": "뭔가이상한값", "reply": "아무말", "why": ""})
assert r["kind"] == "상담" and r["reply"] == "", f"모르는 분류는 사람에게: {r}"
r = 분류시험({"kind": "인사", "reply": "읽어주셔서 감사합니다.", "why": ""})
assert r["kind"] == "인사" and r["reply"], r
print("댓글 자동답글 안전장치 통과: 상담·부정·불명은 답글 없음, 인사만 통과")


# 21시 슬롯: 승인이 없을 때 무엇이 나가고 무엇이 안 나가는지
#   승인 없이 자동으로 나가도 되는 것은 판단이 없는 글뿐이다.
#   임장기는 회원님 메모에서 나온 판단이 들어 있어 반드시 승인을 거쳐야 한다.
from src import main as main_mod  # noqa: E402
from src import notion as notion_mod  # noqa: E402

def 발행시도(승인, 대기):
    보낸것 = []
    notion_mod.enabled = lambda: True
    notion_mod.fetch_approved = lambda: 승인
    notion_mod.fetch_waiting = lambda: 대기
    main_mod.notify.send = lambda *a, **k: 보낸것.append(a[0] if a else "")
    올린것 = []
    main_mod.publish_image_post = lambda text, url: (올린것.append(text), "id1")[1]
    main_mod.publish_reply = lambda *a, **k: "r1"
    main_mod.state_mod.save = lambda *a, **k: None
    main_mod.commit_and_push = lambda *a, **k: None
    notion_mod.mark_published = lambda *a, **k: None
    os.environ["MODE"] = "publish"
    os.environ["DRY_RUN"] = "0"      # 이 시험은 발행 분기 자체를 봐야 한다
    try:
        main_mod.run_publish()
    finally:
        os.environ["DRY_RUN"] = "1"
    return 올린것, 보낸것

뉴스행 = {"page_id": "p1", "title": "t", "text": "본문", "detail": "",
          "card_url": "https://example.com/a.png", "type": "뉴스"}
임장행 = dict(뉴스행, type="임장기")

올림, _ = 발행시도(None, 뉴스행)
assert 올림, "승인이 없어도 뉴스 글은 나가야 한다"
올림, 알림 = 발행시도(None, 임장행)
assert not 올림, "임장기가 승인 없이 나갔다 — 판단이 담긴 글이다"
assert any("승인" in m for m in 알림), 알림
올림, _ = 발행시도(None, None)
assert not 올림, "초안이 없는데 뭔가 올라갔다"
올림, _ = 발행시도(뉴스행, None)
assert 올림, "승인된 글은 당연히 나가야 한다"
print("21시 승인 분기 통과: 임장기는 승인 없이 안 나감, 뉴스는 자동 발행")


# 질문을 쓰지 않는 유형에서 AI 가 질문을 뱉어도 코드가 지운다.
#   프롬프트 지시만으로는 안 막혔다. 방법론 글이 "주차와 경사 중 어느 쪽을
#   먼저 보시나요?" 로 끝나버렸고, 그게 없애려던 바로 그 AI 티였다.
from src import compose as c_mod  # noqa: E402
from src.select import pick_fallback, pick_question  # noqa: E402

def 질문검사(pick):
    c_mod.ask_json = lambda *a, **k: {
        "hook": "제목", "body": "1\n2\n3", "opinion": "",
        "question": "주차와 경사 중 어느 쪽을 먼저 보시나요?",
        "detail": "상세", "card_label": "", "card_number": "",
        "card_headline": "", "source_line": "출처: 매일경제", "tags": [],
    }
    return c_mod.compose(pick)

방법론 = 질문검사(Pick(article=None, score=0, reason="", fallback_topic="임장준비|x"))
assert 방법론.question == "", f"방법론이 질문으로 끝났다: {방법론.question}"
질문글 = 질문검사(Pick(article=None, score=0, reason="", question_topic="현금생기면|x"))
assert 질문글.question, "질문 글에는 질문이 남아야 한다"
assert 질문글.detail == "", "질문 글에 첫 댓글이 붙었다"
print("질문 마무리 통제 통과: 방법론은 제거, 질문 글은 유지")

# 카드를 붙이지 않는 유형은 한 곳에서만 정해진다.
#   08·17시 경로에만 걸어놨더니 21시로 나간 방법론 글에 카드가 붙었다.
assert "방법론" in main_mod.NO_CARD_KINDS and "질문" in main_mod.NO_CARD_KINDS
import inspect  # noqa: E402
for 함수 in (main_mod.run_auto, main_mod.run_draft):
    본문 = inspect.getsource(함수)
    assert "NO_CARD_KINDS" in 본문, f"{함수.__name__} 이 카드 유형을 안 본다"
# 카드 URL 이 비었으면 발행은 글만 올린다
올린것 = []
notion_mod.enabled = lambda: True
notion_mod.fetch_approved = lambda: {"page_id": "p", "title": "t", "text": "본문",
                                     "detail": "", "card_url": "", "type": "방법론"}
notion_mod.mark_published = lambda *a, **k: None
main_mod.notify.send = lambda *a, **k: None
main_mod.notify.published = lambda *a, **k: None
main_mod.publish_text_post = lambda text: (올린것.append("텍스트"), "id")[1]
main_mod.publish_image_post = lambda text, url: (올린것.append("카드"), "id")[1]
main_mod.state_mod.save = lambda *a, **k: None
main_mod.commit_and_push = lambda *a, **k: None
os.environ["DRY_RUN"] = "0"
try:
    main_mod.run_publish()
finally:
    os.environ["DRY_RUN"] = "1"
assert 올린것 == ["텍스트"], f"카드 없는 초안인데 {올린것} 로 나갔다"
print("카드 없는 유형 통과: 초안·발행 양쪽에서 카드가 안 붙음")

sys.exit(code)
