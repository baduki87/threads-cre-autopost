"""소재 겹침 막기 (10-29).

주제 라벨·묶음은 같은 종류 안에서만 돌았다. 그래서 '임대차 현황표'가 방법론 → 질문 → AI 글로
모양만 바꿔 2주에 7번 나왔다. 여기서는 종류를 가리지 않고 **제목에 나온 소재**를 본다.
"""
from __future__ import annotations

from functools import lru_cache

import yaml

from . import state as state_mod

DAYS = 10


@lru_cache(maxsize=1)
def _table(path: str = "config/subjects.yaml") -> dict[str, list[str]]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["subjects"]


def subjects_in(text: str) -> set[str]:
    return {name for name, words in _table().items() if any(w in text for w in words)}


def recent_subjects(st: dict | None, days: int = DAYS) -> set[str]:
    """최근 N일 제목에 나온 소재. 제목 앞의 [라벨]도 함께 본다(AI렌트롤 → 임대차현황표)."""
    if not st:
        return set()
    out: set[str] = set()
    for title in state_mod.recent_titles(st, days=days):
        out |= subjects_in(title)
    return out


def topic_subjects(topic: dict) -> set[str]:
    """주제 하나의 소재. 라벨과 설명 첫 줄만 본다 — 설명 전체를 보면 '건축물대장·등기부에서
    무엇을 보는지' 같은 곁가지까지 걸려 고를 주제가 없어진다."""
    first = str(topic.get("prompt", "")).strip().split("\n")[0]
    return subjects_in(f"{topic.get('label', '')} {first}")


def title_problems(hook: str, recent: set[str], allowed: set[str]) -> list[str]:
    """제목이 최근 10일에 다룬 소재를 또 쓰면 문제. 주제 자체의 소재(allowed)는 봐준다 —
    고를 주제가 다 떨어져 어쩔 수 없이 고른 경우다."""
    clash = (subjects_in(hook) & recent) - allowed
    return [f"제목의 소재 '{s}' 는 최근 {DAYS}일 안에 다른 글에서 이미 다뤘습니다. "
            f"이 주제의 다른 측면을 중심 소재로 삼으세요" for s in sorted(clash)]
