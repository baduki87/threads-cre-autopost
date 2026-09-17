"""글 끝 한 줄을 고른다.

AI 에게 맡기지 않는다. 매번 비슷한 문구를 지어내면 그게 또 기계 신호가 되고,
영업 문구가 슬며시 끼어들 수도 있다. 목록에서 코드가 돌려 고른다.
"""
from __future__ import annotations

import yaml

from . import state as state_mod

PATH = "config/closers.yaml"


def pick(kind: str, st: dict | None = None, path: str = PATH) -> str:
    """유형에 맞는 마무리 한 줄. 최근에 쓴 것은 피한다."""
    try:
        with open(path, encoding="utf-8") as f:
            pool = (yaml.safe_load(f) or {}).get(kind) or []
    except (OSError, yaml.YAMLError):
        return ""
    if not pool:
        return ""

    최근 = set()
    if st:
        # 최근 발행 글에 붙였던 문구는 기록에 남겨두고 피한다.
        최근 = {p.get("closer", "") for p in st.get("posts", [])[-6:]}
    남은 = [c for c in pool if c not in 최근]
    return (남은 or pool)[0]
