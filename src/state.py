"""발행 이력 관리. GitHub Actions 가 매 실행 후 리포에 커밋한다."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

STATE_PATH = "state/published.json"
DRAFTS_PATH = "state/drafts.json"
KST = timezone(timedelta(hours=9))


def _when(record: dict) -> datetime | None:
    """기록의 date 를 시각으로. 깨진 값은 None."""
    try:
        dt = datetime.fromisoformat(record["date"])
    except (KeyError, TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=KST)


def load(path: str = STATE_PATH) -> dict:
    if not os.path.exists(path):
        return {"posts": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(state: dict, path: str = STATE_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def seen_keys(state: dict) -> set[str]:
    return {p["key"] for p in state.get("posts", []) if p.get("key")}


def recent_titles(state: dict, days: int = 21) -> list[str]:
    """최근 N일 안에 다룬 제목. 같은 사안의 후속 기사를 걸러내는 데 쓴다."""
    cutoff = datetime.now(KST) - timedelta(days=days)
    out = []
    for p in state.get("posts", []):
        when = _when(p)
        if when and when >= cutoff:
            out.append(p.get("title", ""))
    return [t for t in out if t]


def _tokens(title: str) -> set[str]:
    """제목에서 두 글자 이상의 낱말만 추린다."""
    return {t for t in re.findall(r"[가-힣A-Za-z0-9]+", title) if len(t) >= 2}


def is_near_duplicate(title: str, previous: list[str], threshold: float = 0.72,
                      overlap: float = 0.4) -> bool:
    """같은 사건을 다룬 기사인가.

    글자 단위 비교만으로는 한글에서 어순이 바뀐 같은 기사를 못 잡는다.
      "용적률 1.2배 높이면 성산시영 분담금 1억 뚝"
      "성산시영 용적률 완화, 분담금 1억 줄어"
    둘의 글자 유사도는 낮지만 같은 기사다. 그래서 낱말 겹침(자카드)도 함께 본다.

    기준을 0.4 로 둔 이유는 '서울 아파트' 처럼 흔한 낱말만 겹치는 다른 기사가
    걸리지 않게 하기 위해서다(그 경우 겹침이 0.2 수준).
    """
    mine = _tokens(title)
    for old in previous:
        if SequenceMatcher(None, title, old).ratio() >= threshold:
            return True
        theirs = _tokens(old)
        if mine and theirs:
            union = mine | theirs
            if union and len(mine & theirs) / len(union) >= overlap:
                return True
    return False


def record(state: dict, *, key: str, title: str, url: str, post_id: str | None,
           kind: str, dry_run: bool, type_: str = "", notion_page: str = "",
           slot: str = "") -> dict:
    """발행 기록 한 줄. 성과(views/likes/replies)는 며칠 뒤 insights 가 채운다."""
    state.setdefault("posts", []).append(
        {
            "date": datetime.now(KST).isoformat(timespec="seconds"),
            "key": key,
            "title": title,
            "url": url,
            "post_id": post_id,
            "kind": kind,
            "type": type_,
            "slot": slot,          # 08 / 17 / 21. 어느 시간대가 잘 되는지 비교용
            "notion_page": notion_page,
            "dry_run": dry_run,
            "views": None,
            "likes": None,
            "replies": None,
        }
    )
    return state


def pending_metrics(state: dict, days_min: int = 3) -> list[dict]:
    """성과를 아직 안 걷은 발행 글. 발행 후 days_min 일이 지난 것만."""
    cutoff = datetime.now(KST) - timedelta(days=days_min)
    out = []
    for p in state.get("posts", []):
        if p.get("dry_run") or not p.get("post_id") or p.get("views") is not None:
            continue
        when = _when(p)
        if when and when <= cutoff:
            out.append(p)
    return out


def apply_metrics(state: dict, post_id: str, *, views: int, likes: int,
                  replies: int) -> bool:
    for p in state.get("posts", []):
        if p.get("post_id") == post_id:
            p["views"], p["likes"], p["replies"] = views, likes, replies
            return True
    return False


# ------------------------------------------------- 초안 → 발행 사이의 소재 기록

def remember_draft(page_id: str, *, key: str, title: str,
                   path: str = DRAFTS_PATH) -> None:
    """19시 초안이 어떤 기사에서 나왔는지 적어둔다.

    21시 발행 단계는 노션 행만 본다. 그런데 노션에는 AI 가 다시 쓴 제목밖에
    없어서, 그걸 그대로 기록하면 원본 기사 키가 이력에 영영 남지 않는다.
    그러면 다음 날 08시가 같은 기사를 아무 제지 없이 다시 뽑는다.
    """
    data = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            data = {}

    data[page_id] = {
        "key": key,
        "title": title,
        "date": datetime.now(KST).isoformat(timespec="seconds"),
    }
    # 승인 없이 지나간 초안이 계속 쌓이므로 2주 지난 것은 버린다.
    cutoff = datetime.now(KST) - timedelta(days=14)
    data = {k: v for k, v in data.items()
            if (_when(v) or datetime.now(KST)) >= cutoff}

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def recall_draft(page_id: str, path: str = DRAFTS_PATH) -> dict | None:
    """remember_draft 로 적어둔 원본 소재. 없으면 None."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get(page_id)
    except (OSError, json.JSONDecodeError):
        return None
