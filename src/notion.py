"""노션 연동.

노션은 **원천이 아니다.** 진짜 기록은 state/published.json 이고,
노션은 사람이 보는 화면 + 메모를 넣는 창구다.
그래서 이 모듈의 모든 함수는 실패해도 예외를 밖으로 던지지 않는다.
노션이 멈춰도 발행은 계속돼야 한다.

DB 속성 (docs/SETUP.md 에 만드는 법이 있다):
  제목(Title) / 상태(Select) / 본문(Text) / 상세(Text) / 유형(Select) / 카드(URL)
  발행일(Date) / post_id(Text) / 조회수·좋아요·댓글(Number) / 메모(Text)
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import requests

from .models import Memo

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
KST = timezone(timedelta(hours=9))

# 상태값
MEMO = "메모"
WAITING = "대기"
APPROVED = "승인"
PUBLISHED = "발행됨"

# 노션 rich_text 는 블록당 2000자 제한이 있다.
_RICH_LIMIT = 2000


def enabled() -> bool:
    return bool(os.environ.get("NOTION_TOKEN") and os.environ.get("NOTION_DB_ID"))


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['NOTION_TOKEN']}",
        "Notion-Version": VERSION,
        "Content-Type": "application/json",
    }


def _call(method: str, path: str, **kwargs) -> dict | None:
    """노션 호출 한 곳. 실패는 경고만 남기고 None 을 돌려준다."""
    if not enabled():
        return None
    try:
        r = requests.request(
            method, f"{API}{path}", headers=_headers(), timeout=30, **kwargs
        )
        if not r.ok:
            print(f"[notion] {method} {path} 실패 {r.status_code}: {r.text[:200]}",
                  file=sys.stderr)
            return None
        return r.json()
    except requests.RequestException as e:
        print(f"[notion] {method} {path} 연결 실패: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------- 값 변환

def _rich(text: str) -> list[dict]:
    return [{"type": "text", "text": {"content": (text or "")[:_RICH_LIMIT]}}]


def _plain(prop: dict | None) -> str:
    """title / rich_text 속성에서 순수 텍스트를 뽑는다."""
    if not prop:
        return ""
    items = prop.get("title") or prop.get("rich_text") or []
    return "".join(i.get("plain_text", "") for i in items).strip()


def _select(prop: dict | None) -> str:
    if not prop or not prop.get("select"):
        return ""
    return prop["select"].get("name", "")


# ---------------------------------------------------------------- 읽기

def fetch_memo() -> Memo | None:
    """상태가 '메모'인 행 중 가장 오래된 것 하나.

    메모는 의견의 유일한 출처다. 있으면 뉴스보다 우선한다.
    """
    data = _call(
        "POST", f"/databases/{os.environ.get('NOTION_DB_ID', '')}/query",
        json={
            "filter": {"property": "상태", "select": {"equals": MEMO}},
            "sorts": [{"timestamp": "created_time", "direction": "ascending"}],
            "page_size": 1,
        },
    )
    if not data or not data.get("results"):
        return None

    page = data["results"][0]
    props = page.get("properties", {})
    text = _plain(props.get("메모")) or _plain(props.get("본문"))
    if not text:
        print("[notion] 메모 행을 찾았지만 내용이 비어 있습니다.", file=sys.stderr)
        return None

    memo = Memo(
        page_id=page["id"],
        title=_plain(props.get("제목")),
        text=text,
    )
    print(f"[notion] 메모 발견: {memo.title[:40] or '(제목 없음)'}")
    return memo


def fetch_approved() -> dict | None:
    """상태가 '승인'인 행 하나. 발행 단계가 이것만 올린다.

    반환: {page_id, text, card_url, type, title}
    """
    data = _call(
        "POST", f"/databases/{os.environ.get('NOTION_DB_ID', '')}/query",
        json={
            "filter": {"property": "상태", "select": {"equals": APPROVED}},
            "sorts": [{"timestamp": "created_time", "direction": "ascending"}],
            "page_size": 1,
        },
    )
    if not data or not data.get("results"):
        return None

    page = data["results"][0]
    props = page.get("properties", {})
    body = _plain(props.get("본문"))
    if not body:
        print("[notion] 승인된 행의 본문이 비어 있어 건너뜁니다.", file=sys.stderr)
        return None

    return {
        "page_id": page["id"],
        "title": _plain(props.get("제목")),
        "text": body,
        "detail": _plain(props.get("상세")),
        "card_url": (props.get("카드") or {}).get("url") or "",
        "type": _select(props.get("유형")),
    }


def published_pages(days_min: int = 3, limit: int = 50) -> list[dict]:
    """발행된 지 days_min 일 이상 지난 행. 성과 수집 대상."""
    cutoff = (datetime.now(KST) - timedelta(days=days_min)).date().isoformat()
    data = _call(
        "POST", f"/databases/{os.environ.get('NOTION_DB_ID', '')}/query",
        json={
            "filter": {
                "and": [
                    {"property": "상태", "select": {"equals": PUBLISHED}},
                    {"property": "발행일", "date": {"on_or_before": cutoff}},
                ]
            },
            "page_size": limit,
        },
    )
    if not data:
        return []
    out = []
    for page in data.get("results", []):
        props = page.get("properties", {})
        pid = _plain(props.get("post_id"))
        if pid:
            out.append({"page_id": page["id"], "post_id": pid,
                        "title": _plain(props.get("제목"))})
    return out


# ---------------------------------------------------------------- 쓰기

def create_draft(*, title: str, text: str, card_url: str, kind: str,
                 detail: str = "") -> str | None:
    """초안을 '대기' 상태로 올린다. 회원님이 승인하면 발행된다.

    detail 은 발행 직후 첫 댓글로 붙는다. 노션에서 직접 고칠 수 있다.
    """
    data = _call(
        "POST", "/pages",
        json={
            "parent": {"database_id": os.environ.get("NOTION_DB_ID", "")},
            "properties": {
                "제목": {"title": _rich(title or "(제목 없음)")},
                "상태": {"select": {"name": WAITING}},
                "본문": {"rich_text": _rich(text)},
                "상세": {"rich_text": _rich(detail)},
                "유형": {"select": {"name": kind}},
                **({"카드": {"url": card_url}} if card_url else {}),
            },
        },
    )
    if not data:
        return None
    print(f"[notion] 초안 등록 완료 — 노션에서 확인 후 상태를 '{APPROVED}' 로 바꾸세요")
    return data.get("id")


def mark_published(page_id: str, post_id: str) -> None:
    _call(
        "PATCH", f"/pages/{page_id}",
        json={
            "properties": {
                "상태": {"select": {"name": PUBLISHED}},
                "post_id": {"rich_text": _rich(post_id)},
                "발행일": {"date": {"start": datetime.now(KST).date().isoformat()}},
            }
        },
    )


def mark_memo_used(page_id: str) -> None:
    """메모를 초안으로 바꿨으면 '대기'로 옮겨 다시 뽑히지 않게 한다."""
    _call("PATCH", f"/pages/{page_id}",
          json={"properties": {"상태": {"select": {"name": WAITING}}}})


def update_metrics(page_id: str, *, views: int, likes: int, replies: int) -> None:
    _call(
        "PATCH", f"/pages/{page_id}",
        json={
            "properties": {
                "조회수": {"number": views},
                "좋아요": {"number": likes},
                "댓글": {"number": replies},
            }
        },
    )


def check() -> tuple[bool, str]:
    """준비 상태 점검용. (성공여부, 설명)"""
    if not enabled():
        return False, "NOTION_TOKEN / NOTION_DB_ID 미설정"
    data = _call("GET", f"/databases/{os.environ['NOTION_DB_ID']}")
    if not data:
        return False, "DB 조회 실패 — 토큰이 맞는지, DB 에 통합을 연결했는지 확인하세요"

    have = set(data.get("properties", {}).keys())
    need = {"제목", "상태", "본문", "상세", "유형", "카드", "발행일", "post_id",
            "조회수", "좋아요", "댓글", "메모"}
    missing = need - have
    if missing:
        return False, f"DB 속성 누락: {', '.join(sorted(missing))}"
    title = "".join(t.get("plain_text", "") for t in data.get("title", []))
    return True, f"DB '{title}' 연결 정상 — 속성 {len(need)}개 확인"


if __name__ == "__main__":
    ok, msg = check()
    print(("OK " if ok else "실패 ") + msg)
