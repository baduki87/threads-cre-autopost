"""파이프라인 오케스트레이션.

두 단계로 나뉜다.

  MODE=auto    (08시, 17시) 초안을 만들어 바로 발행한다. 승인 없음
  MODE=draft   (19시)       메모/뉴스로 초안을 만들어 노션에 '대기'로 올린다
  MODE=publish (21시)       노션에서 '승인'된 것만 실제로 발행한다

하루 3건이라 승인을 세 번 받으면 지속이 어렵다. 주력인 21시만 승인을 거치고
나머지 두 슬롯은 자동으로 나간다. 메모가 있는 날은 21시가 가져간다 —
판단이 담긴 글은 최고 시간대에 확인을 거쳐 나가는 게 맞다.

SLOT 은 카드 파일명과 성과 기록에 쓴다. 하루 3건이면 파일명이 겹쳐
앞 글의 이미지가 덮어써진다.

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


def _slot() -> str:
    """08 / 17 / 21. 지정이 없으면 현재 시각에서 가장 가까운 슬롯."""
    given = os.environ.get("SLOT", "").strip()
    if given:
        return given.zfill(2)
    hour = datetime.now(KST).hour
    return min(("08", "17", "21"), key=lambda s: abs(int(s) - hour))


def _card_path(today: str, slot: str, dry_run: bool) -> str:
    """슬롯을 파일명에 넣는다. 안 넣으면 하루 3건이 같은 파일을 덮어쓴다."""
    folder = "out" if dry_run else "docs/img"
    return f"{folder}/{today}-{slot}.png"


# ---------------------------------------------------------------- 초안

def _build_post(st: dict, *, allow_memo: bool):
    """소재를 골라 글 하나를 만든다. (post, kind, memo, pick) 을 돌려준다.

    allow_memo=False 인 자동 슬롯은 메모를 건드리지 않는다.
    메모가 담긴 글은 판단이 들어가므로 승인을 거치는 21시 슬롯의 몫이다.
    """
    memo = notion.fetch_memo() if (allow_memo and notion.enabled()) else None
    if memo:
        pick = Pick(article=None, score=10, reason="현장 메모", memo=memo)
        kind = "임장기"
    else:
        cfg = load_config()
        articles = collect(cfg)
        if not articles:
            print("[main] 수집 결과 0건 — 백업 콘텐츠로 진행합니다.")
        pick = select(articles, st)
        kind = "뉴스" if not pick.is_fallback else "방법론"

    return compose(pick, state=st), kind, memo, pick


def _source_id(pick: Pick, post, today: str, slot: str) -> tuple[str, str]:
    """이력에 남길 (key, title).

    key 는 다음 슬롯이 같은 기사를 다시 뽑지 못하게 하는 근거이고,
    title 은 '같은 사건의 다른 기사' 를 걸러내는 비교 대상이다.
    그래서 둘 다 **원본 기사** 것이어야 한다. AI 가 다시 쓴 제목을 넣으면
    어순과 표현이 달라져 비교가 헐거워지고, 같은 소재가 또 나간다.
    """
    if pick.article:
        return pick.article.key, pick.article.title
    if pick.is_fallback:
        label = (pick.fallback_topic or "|").split("|", 1)[0]
        # 백업 주제는 label 을 제목에 남긴다. pick_fallback 이 이걸 보고 회전한다.
        return f"fallback-{label}-{today}", f"[{label}] {post.hook}"
    return f"memo-{today}-{slot}", post.hook or today


def run_auto() -> int:
    """08 / 17 시 슬롯. 초안을 만들어 바로 발행한다."""
    dry_run = _truthy("DRY_RUN")
    account = os.environ.get("THREADS_ACCOUNT_HANDLE", "")
    today, slot = _today(), _slot()
    print(f"=== {today} {slot}시 자동 발행 (DRY_RUN={dry_run}) ===")

    st = state_mod.load()
    post, kind, _, pick = _build_post(st, allow_memo=False)
    text = post.render_text()

    print("\n--- 본문 ---")
    print(text)
    print(f"--- ({len(text)}자) ---\n")

    card_path = _card_path(today, slot, dry_run)
    render(post, card_path, account=account)

    detail = post.render_detail()
    if dry_run:
        os.makedirs("out", exist_ok=True)
        with open(f"out/{today}-{slot}.txt", "w", encoding="utf-8") as f:
            f.write(text + "\n")
        if detail:
            print(f"--- 첫 댓글 ---\n{detail}\n")
        print(f"[auto] DRY_RUN — 발행하지 않았습니다. {card_path} 를 확인하세요.")
        return 0

    commit_and_push([card_path], f"card: {today}-{slot}")
    post_id = publish_image_post(text, raw_url_for(card_path))

    if detail:
        try:
            publish_reply(detail[:500], post_id)
        except Exception as e:
            print(f"[auto] 첫 댓글 실패 (본문은 정상 발행됨): {e}", file=sys.stderr)

    src_key, src_title = _source_id(pick, post, today, slot)
    state_mod.record(
        st,
        key=src_key,
        title=src_title,
        url=pick.article.url if pick.article else "",
        post_id=post_id,
        kind="auto",
        type_=kind,
        slot=slot,
        dry_run=False,
    )
    state_mod.save(st)
    commit_and_push([state_mod.STATE_PATH], f"state: {today}-{slot} 발행 기록")

    # 자동 발행은 성공 시 조용히 넘어간다. 하루 세 번 알림은 피로하다.
    notion.create_published(title=post.hook or today, text=text, detail=detail,
                            kind=kind, post_id=post_id,
                            card_url=raw_url_for(card_path))
    return 0


def run_draft() -> int:
    dry_run = _truthy("DRY_RUN")
    account = os.environ.get("THREADS_ACCOUNT_HANDLE", "")
    today, slot = _today(), _slot()
    print(f"=== {today} 초안 생성 (DRY_RUN={dry_run}) ===")

    st = state_mod.load()
    post, kind, memo, pick = _build_post(st, allow_memo=True)
    text = post.render_text()

    print("\n--- 초안 ---")
    print(text)
    print(f"--- ({len(text)}자) ---\n")

    card_path = _card_path(today, slot, dry_run)
    render(post, card_path, account=account)

    if dry_run:
        os.makedirs("out", exist_ok=True)
        with open(f"out/{today}-{slot}.txt", "w", encoding="utf-8") as f:
            f.write(text + "\n")
        detail = post.render_detail()
        if detail:
            print(f"\n--- 첫 댓글 ---\n{detail}\n--- ({len(detail)}자) ---")
        print(f"[draft] DRY_RUN — 노션에 쓰지 않았습니다. {card_path} 를 확인하세요.")
        return 0

    if not notion.enabled():
        print("[draft] 노션이 설정되지 않아 초안을 저장할 곳이 없습니다.", file=sys.stderr)
        return 1

    # 카드를 먼저 커밋해야 공개 URL 이 생긴다. 노션에도 그 URL 을 넣는다.
    commit_and_push([card_path], f"card: {today}-{slot}")
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

    # 어떤 기사에서 나온 초안인지 남긴다. 21시 발행이 이걸 읽어 이력에 적는다.
    src_key, src_title = _source_id(pick, post, today, slot)
    state_mod.remember_draft(page_id, key=src_key, title=src_title)
    commit_and_push([state_mod.DRAFTS_PATH], f"draft: {today}-{slot} 소재 기록")

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
    # 초안 단계에서 적어둔 원본 기사. 없으면(수동으로 만든 행 등) 노션 값으로 대체한다.
    src = state_mod.recall_draft(row["page_id"]) or {}
    state_mod.record(
        st,
        key=src.get("key") or f"notion-{row['page_id']}",
        title=src.get("title") or row["title"] or text.split("\n", 1)[0],
        url="",
        post_id=post_id,
        kind="notion",
        type_=row.get("type", ""),
        slot=_slot(),
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
    if mode == "auto":
        return run_auto()
    print(f"[main] 알 수 없는 MODE '{mode}' — auto / draft / publish 중 하나입니다.",
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
