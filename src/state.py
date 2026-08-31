"""발행 이력 관리. GitHub Actions 가 매 실행 후 리포에 커밋한다."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

STATE_PATH = "state/published.json"
KST = timezone(timedelta(hours=9))


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
        try:
            when = datetime.fromisoformat(p["date"])
        except (KeyError, ValueError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=KST)
        if when >= cutoff:
            out.append(p.get("title", ""))
    return [t for t in out if t]


def is_near_duplicate(title: str, previous: list[str], threshold: float = 0.72) -> bool:
    for old in previous:
        if SequenceMatcher(None, title, old).ratio() >= threshold:
            return True
    return False


def record(state: dict, *, key: str, title: str, url: str, post_id: str | None,
           kind: str, dry_run: bool) -> dict:
    state.setdefault("posts", []).append(
        {
            "date": datetime.now(KST).isoformat(timespec="seconds"),
            "key": key,
            "title": title,
            "url": url,
            "post_id": post_id,
            "kind": kind,
            "dry_run": dry_run,
        }
    )
    return state
