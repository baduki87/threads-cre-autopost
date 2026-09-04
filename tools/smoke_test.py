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
        "hook": "1주택자 갈아타기 대출 규제 바뀜",
        "body": "수도권 주담대 한도 조정\n실행일 기준으로 적용\n기존 계약분은 종전 기준 유지",
        # 메모가 없는 날이라 의견을 넣어봤지만 compose 가 걸러내야 한다 (안전장치 회귀 테스트)
        "opinion": "지금이 매수 기회로 보임",
        "question": "스친들은 이번 규제로 계획 바뀐 거 있어?",
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

sys.exit(code)
