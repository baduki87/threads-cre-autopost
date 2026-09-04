"""성과 수집. 학습 루프를 닫는 조각이다.

발행 기록만 쌓으면 그냥 일기장이다. 며칠 뒤 조회수를 다시 걷어와
같은 레코드에 채워야 다음 초안이 그걸 보고 배운다.

Threads API: GET /v1.0/{mediaId}/insights?metric=views,likes,replies,reposts
필요 권한: threads_manage_insights (토큰 재발급 필요)
"""
from __future__ import annotations

import os
import sys

import requests

from . import notion
from . import state as state_mod
from .publish import API, PublishError, commit_and_push

METRICS = "views,likes,replies,reposts"


def fetch_metrics(post_id: str, token: str) -> dict[str, int] | None:
    """한 글의 지표. 실패하면 None — 다음 실행에서 다시 시도한다."""
    try:
        r = requests.get(
            f"{API}/{post_id}/insights",
            params={"metric": METRICS, "access_token": token},
            timeout=30,
        )
    except requests.RequestException as e:
        print(f"[insights] {post_id} 연결 실패: {e}", file=sys.stderr)
        return None

    if r.status_code == 400 and "permission" in r.text.lower():
        print(f"[insights] 권한 부족 — 토큰에 threads_manage_insights 가 필요합니다.\n"
              f"  {r.text[:200]}", file=sys.stderr)
        return None
    if not r.ok:
        print(f"[insights] {post_id} HTTP {r.status_code}: {r.text[:200]}", file=sys.stderr)
        return None

    out: dict[str, int] = {}
    for item in r.json().get("data", []):
        name = item.get("name")
        values = item.get("values") or []
        if name and values:
            out[name] = int(values[0].get("value", 0) or 0)
    return out


def run(days_min: int = 3) -> int:
    token = os.environ.get("THREADS_ACCESS_TOKEN")
    if not token:
        raise PublishError("THREADS_ACCESS_TOKEN 이 설정되지 않았습니다.")

    st = state_mod.load()
    targets = state_mod.pending_metrics(st, days_min=days_min)
    if not targets:
        print(f"[insights] 성과를 걷을 글이 없습니다 (발행 후 {days_min}일 경과 대상).")
        return 0

    print(f"[insights] 대상 {len(targets)}건")
    updated = 0
    for p in targets:
        m = fetch_metrics(p["post_id"], token)
        if m is None:
            continue
        views = m.get("views", 0)
        likes = m.get("likes", 0)
        replies = m.get("replies", 0)
        state_mod.apply_metrics(st, p["post_id"], views=views, likes=likes, replies=replies)
        updated += 1
        print(f"  {p.get('title', '')[:40]} — 조회 {views} / 좋아요 {likes} / 댓글 {replies}")

        page = p.get("notion_page")
        if page and notion.enabled():
            notion.update_metrics(page, views=views, likes=likes, replies=replies)

    if not updated:
        print("[insights] 갱신된 항목이 없습니다.")
        return 0

    state_mod.save(st)
    try:
        commit_and_push([state_mod.STATE_PATH], f"insights: {updated}건 성과 반영")
    except Exception as e:   # 로컬 실행 등 git 환경이 아닐 수 있다
        print(f"[insights] 커밋 생략: {e}", file=sys.stderr)
    print(f"[insights] {updated}건 반영 완료")
    return 0


if __name__ == "__main__":
    sys.exit(run())
