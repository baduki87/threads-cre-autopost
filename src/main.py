"""파이프라인 오케스트레이션.

두 단계로 나뉜다.

  MODE=draft   (저녁 7시) 메모/뉴스로 초안을 만들어 노션에 '대기'로 올린다
  MODE=publish (밤 9시)   노션에서 '승인'된 것만 실제로 발행한다

승인이 없으면 발행하지 않는다. 빈 글이 나가는 것보다 낫다.
DRY_RUN=1 이면 바깥에 아무것도 쓰지 않고 out/ 에만 남긴다.
"""
from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime, timedelta, timezone

from . import notify
from . import notion
from . import state as state_mod
from .card import render
from .collect import collect, load_config
from .compose import compose
from .models import Pick
from .publish import (PublishError, commit_and_push, publish_image_post,
                      publish_reply, raw_url_for)
from .select import select

KST = timezone(timedelta(hours=9))
NOTION_PAGE_URL = os.environ.get(
    "NOTION_PAGE_URL",
    "https://www.notion.so/bcb85698aaa5474e9c4d5a5f5716dc1f",
)


def _truthy(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _today() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- 초안

def run_draft() -> int:
    dry_run = _truthy("DRY_RUN")
    account = os.environ.get("THREADS_ACCOUNT_HANDLE", "")
    today = _today()
    print(f"=== {today} 초안 생성 (DRY_RUN={dry_run}) ===")

    st = state_mod.load()

    # 메모가 있으면 무조건 우선한다. 의견은 메모에서만 나온다.
    memo = notion.fetch_memo() if notion.enabled() else None
    if memo:
        pick = Pick(article=None, score=10, reason="현장 메모", memo=memo)
        kind = "임장기"
    else:
        cfg = load_config()
        articles = collect(cfg)
        if not articles:
            print("[draft] 수집 결과 0건 — 백업 콘텐츠로 진행합니다.")
        pick = select(articles, st)
        kind = "뉴스" if not pick.is_fallback else "방법론"

    post = compose(pick, state=st)
    text = post.render_text()

    print("\n--- 초안 ---")
    print(text)
    print(f"--- ({len(text)}자) ---\n")

    card_path = f"out/{today}.png" if dry_run else f"docs/img/{today}.png"
    render(post, card_path, account=account)

    if dry_run:
        os.makedirs("out", exist_ok=True)
        with open(f"out/{today}.txt", "w", encoding="utf-8") as f:
            f.write(text + "\n")
        detail = post.render_detail()
        if detail:
            with open(f"out/{today}-댓글.txt", "w", encoding="utf-8") as f:
                f.write(detail + "\n")
            print(f"\n--- 첫 댓글 ---\n{detail}\n--- ({len(detail)}자) ---")
        print(f"[draft] DRY_RUN — 노션에 쓰지 않았습니다. out/{today}.* 를 확인하세요.")
        return 0

    if not notion.enabled():
        print("[draft] 노션이 설정되지 않아 초안을 저장할 곳이 없습니다.", file=sys.stderr)
        return 1

    # 카드를 먼저 커밋해야 공개 URL 이 생긴다. 노션에도 그 URL 을 넣는다.
    commit_and_push([card_path], f"card: {today}")
    card_url = raw_url_for(card_path)

    page_id = notion.create_draft(
        title=post.hook or today, text=text, card_url=card_url, kind=kind,
        detail=post.render_detail(),
    )
    if not page_id:
        print("[draft] 노션 등록 실패 — 카드는 커밋됐으니 수동으로 올려도 됩니다.",
              file=sys.stderr)
        notify.failed("초안", "노션에 초안을 저장하지 못했습니다.")
        return 1
    if memo:
        notion.mark_memo_used(memo.page_id)

    notify.draft_ready(post.hook or today, text, NOTION_PAGE_URL)
    return 0


# ---------------------------------------------------------------- 발행

def run_publish() -> int:
    dry_run = _truthy("DRY_RUN")
    today = _today()
    print(f"=== {today} 발행 (DRY_RUN={dry_run}) ===")

    if not notion.enabled():
        print("[publish] 노션이 설정되지 않았습니다. 승인 흐름에는 노션이 필요합니다.",
              file=sys.stderr)
        return 1

    row = notion.fetch_approved()
    if not row:
        print("[publish] 승인된 초안이 없습니다. 오늘은 발행하지 않습니다.")
        notify.send("승인된 초안이 없어 오늘은 발행하지 않았습니다.",
                    NOTION_PAGE_URL, "노션 열기")
        return 0

    text, card_url = row["text"], row["card_url"]
    print("\n--- 발행 본문 ---")
    print(text)
    print(f"--- ({len(text)}자) ---\n")

    if len(text) > 500:
        print(f"[publish] 본문이 {len(text)}자로 500자를 넘습니다. 노션에서 줄여주세요.",
              file=sys.stderr)
        return 1
    if not card_url:
        print("[publish] 카드 이미지 URL 이 비어 있습니다.", file=sys.stderr)
        return 1

    if dry_run:
        print("[publish] DRY_RUN — 실제로 발행하지 않았습니다.")
        return 0

    post_id = publish_image_post(text, card_url)

    # 첫 댓글은 부가 기능이다. 실패해도 이미 올라간 본문을 되돌릴 수 없으니
    # 예외를 격리하고 기록만 남긴다.
    detail = row.get("detail", "").strip()
    if detail:
        try:
            publish_reply(detail[:500], post_id)
        except Exception as e:
            print(f"[publish] 첫 댓글 실패 (본문은 정상 발행됨): {e}", file=sys.stderr)
    else:
        print("[publish] 상세가 비어 있어 첫 댓글은 달지 않습니다.")

    st = state_mod.load()
    state_mod.record(
        st,
        key=f"notion-{row['page_id']}",
        title=row["title"] or text.split("\n", 1)[0],
        url="",
        post_id=post_id,
        kind="notion",
        type_=row.get("type", ""),
        notion_page=row["page_id"],
        dry_run=False,
    )
    state_mod.save(st)
    commit_and_push([state_mod.STATE_PATH], f"state: {today} 발행 기록")

    notion.mark_published(row["page_id"], post_id)
    notify.published(row["title"] or today, post_id, with_reply=bool(detail))
    return 0


def run() -> int:
    mode = os.environ.get("MODE", "draft").strip().lower()
    if mode == "publish":
        return run_publish()
    if mode == "draft":
        return run_draft()
    print(f"[main] 알 수 없는 MODE '{mode}' — draft 또는 publish 를 쓰세요.",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(run())
    except PublishError as e:
        print(f"[main] 발행 오류: {e}", file=sys.stderr)
        notify.failed(os.environ.get("MODE", "draft"), str(e))
        sys.exit(1)
    except Exception as e:
        traceback.print_exc()
        notify.failed(os.environ.get("MODE", "draft"), f"{type(e).__name__}: {e}")
        sys.exit(1)
