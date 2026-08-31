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
        "hook": "서울 A급 오피스 공실률이 2.4%로 내려왔습니다.",
        "body": "3분기 연속 하락이고 강남권은 1%대입니다. 신규 공급은 2027년까지 제한적입니다.",
        "takeaway": "임대인 우위 국면이 이어지는 만큼, 재계약 시점이 몰린 자산일수록 임대료 반영이 빠를 여지가 있습니다.",
        "card_label": "오피스",
        "card_number": "2.4%",
        "card_headline": "서울 A급 오피스 공실률 3분기 연속 하락",
        "source_line": "출처: 국토교통부",
        "tags": ["상업용부동산", "오피스"],
    }


llm.ask_json = fake_ask_json
select_mod.ask_json = fake_ask_json
compose_mod.ask_json = fake_ask_json

os.environ["DRY_RUN"] = "1"
os.environ.setdefault("THREADS_ACCOUNT_HANDLE", "@commercial.re")

from src.main import run  # noqa: E402  (스텁 주입 후에 임포트해야 한다)

code = run()

print(f"\nLLM 호출 순서: {CALLS}")

# 500자 제한 회귀 테스트 — 과하게 긴 응답도 잘려야 한다
long_post = Post(
    hook="가" * 100,
    body="나" * 300,
    takeaway="다" * 200,
    card_label="테스트",
    card_number="1",
    card_headline="테스트",
    source_line="출처: 테스트",
    tags=["가", "나", "다"],
)
rendered = long_post.render_text()
assert len(rendered) <= 500, f"500자 제한 위반: {len(rendered)}자"
print(f"길이 제한 테스트 통과: {len(rendered)}자")

sys.exit(code)
