"""파이프라인 오케스트레이션.

DRY_RUN=1 이면 발행 직전까지만 수행하고 결과물을 out/ 에 남긴다.
초기 며칠은 이 모드로 돌려 품질을 눈으로 검증한 뒤 자동 발행을 켠다.
"""
from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime, timedelta, timezone

from . import state as state_mod
from .card import render
from .collect import collect, load_config
from .compose import compose
from .publish import PublishError, commit_and_push, publish_image_post, raw_url_for
from .select import select

KST = timezone(timedelta(hours=9))


def _truthy(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def run() -> int:
    dry_run = _truthy("DRY_RUN")
    account = os.environ.get("THREADS_ACCOUNT_HANDLE", "")
    today = datetime.now(KST).strftime("%Y-%m-%d")
    print(f"=== {today} 실행 (DRY_RUN={dry_run}) ===")

    cfg = load_config()
    articles = collect(cfg)
    if not articles:
        print("[main] 수집 결과 0건 — 백업 콘텐츠로 진행합니다.")

    st = state_mod.load()
    pick = select(articles, st)
    post = compose(pick)

    text = post.render_text()
    print("\n--- 발행 본문 ---")
    print(text)
    print(f"--- ({len(text)}자) ---\n")

    card_path = f"out/{today}.png" if dry_run else f"docs/img/{today}.png"
    render(post, card_path, account=account)

    if dry_run:
        with open(f"out/{today}.txt", "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"[main] DRY_RUN — 발행하지 않았습니다. out/{today}.png / .txt 를 확인하세요.")
        return 0

    # Threads 는 공개 URL 로만 이미지를 받는다. 먼저 커밋해서 URL 을 확보한다.
    commit_and_push([card_path], f"card: {today}")
    image_url = raw_url_for(card_path)
    print(f"[main] 이미지 URL {image_url}")

    post_id = publish_image_post(text, image_url)

    state_mod.record(
        st,
        key=pick.article.key if pick.article else f"fallback-{today}",
        title=pick.article.title if pick.article else post.hook,
        url=pick.article.url if pick.article else "",
        post_id=post_id,
        kind="fallback" if pick.is_fallback else pick.article.kind,
        dry_run=False,
    )
    state_mod.save(st)
    commit_and_push([state_mod.STATE_PATH], f"state: {today} 발행 기록")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(run())
    except PublishError as e:
        print(f"[main] 발행 오류: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
