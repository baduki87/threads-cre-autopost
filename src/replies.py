"""댓글 답글.

모든 댓글에 자동으로 답하지 않는다. 이유가 둘이다.

1. 부동산 댓글에는 "지금 사도 될까요" 같은 투자 자문 질문이 반드시 달린다.
   AI 가 여기에 답하면 공인중개사 이름을 달고 나간 판단이 된다.
2. **그 댓글이 바로 상담이 시작되는 지점이다.** AI 가 먼저 답해버리면
   회원님이 직접 대화를 열 기회가 사라진다. 안전 문제이기 전에 손해다.

그래서 분류부터 한다.

  인사·호응   → 자동 답글. 판단이 안 들어간다
  사실 질문   → 자동 답글. 원글에 있는 사실만 옮긴다
  상담·자문   → **답글 안 함.** 카카오톡으로 모아 알리고 회원님이 직접 답한다
  부정·시비   → **답글 안 함.** 수용 답글은 단지 사정을 알아야 해서 자동화가 위험하다

본문 파이프라인의 규칙("의견은 메모에서만")과 같은 원칙이다.
AI 는 사실을 옮기고, 판단은 사람이 한다.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import requests

from . import notify
from . import state as state_mod
from .llm import ask_json
from .publish import PublishError, publish_reply

API = "https://graph.threads.net/v1.0"
KST = timezone(timedelta(hours=9))

# 자동으로 답글을 다는 분류. 나머지는 사람에게 넘긴다.
AUTO_KINDS = {"인사", "사실질문"}
HUMAN_KINDS = {"상담", "부정"}

# 답글을 다는 대상 기간. 오래된 글에 뒤늦게 답글이 달리는 것까지 쫓지 않는다.
LOOKBACK_DAYS = 7


def _stamp(value: str | None) -> datetime | None:
    """Threads 가 주는 '2026-09-07T00:40:31+0000' 형태를 시각으로."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("+0000", "+00:00"))
    except ValueError:
        return None


def _creds() -> tuple[str, str]:
    token = os.environ.get("THREADS_ACCESS_TOKEN")
    user_id = os.environ.get("THREADS_USER_ID")
    if not token or not user_id:
        raise PublishError("THREADS_ACCESS_TOKEN / THREADS_USER_ID 가 설정되지 않았습니다.")
    return token, user_id


def recent_posts(days: int = LOOKBACK_DAYS) -> list[dict]:
    """최근 N일 안에 올린 내 글. 손으로 올린 글도 포함된다."""
    token, user_id = _creds()
    r = requests.get(
        f"{API}/{user_id}/threads",
        params={"fields": "id,text,timestamp", "limit": 50, "access_token": token},
        timeout=30,
    )
    if not r.ok:
        raise PublishError(f"글 목록 조회 실패 ({r.status_code}): {r.text[:300]}")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for item in r.json().get("data", []):
        when = _stamp(item.get("timestamp"))
        if when and when >= cutoff:
            out.append(item)
    return out


def fetch_replies(post_id: str) -> list[dict]:
    """글 하나에 달린 남의 답글.

    주의: `/{user_id}/replies` 를 쓰면 안 된다. 그건 **내가 쓴** 답글 목록이라
    남의 댓글이 하나도 안 나온다(계정 답글 25건이 전부 내 것이었다).
    답글은 글 단위로 읽어야 한다. `conversation` 은 답글에 달린 답글까지
    한 번에 돌려주므로 `replies` 대신 이쪽을 쓴다.
    """
    token, _ = _creds()
    r = requests.get(
        f"{API}/{post_id}/conversation",
        params={
            "fields": "id,text,username,timestamp,is_reply_owned_by_me",
            "limit": 50,
            "access_token": token,
        },
        timeout=30,
    )
    if not r.ok:
        print(f"[replies] {post_id} 답글 조회 실패 ({r.status_code}) — 건너뜁니다",
              file=sys.stderr)
        return []

    out = []
    for item in r.json().get("data", []):
        if item.get("is_reply_owned_by_me"):
            continue          # 내가 단 첫 댓글이나 내 답글
        if not (item.get("text") or "").strip():
            continue          # 이미지만 있는 답글
        item["root_post_id"] = post_id
        out.append(item)
    return out


SYSTEM = """당신은 서울 아파트를 다루는 공인중개사의 스레드 계정을 돕습니다.
계정 주인은 6년차 부동산 투자자이자 공인중개사입니다.

댓글을 분류하고, 자동으로 답해도 되는 것만 답글 초안을 씁니다.

## 분류

- `인사`: 감사·칭찬·공감·이모지·가벼운 의견 표명. 질문이 없습니다
- `사실질문`: 원글에 있는 내용을 되묻습니다.
  ("언제부터 적용되나요", "그게 무슨 뜻인가요", "어느 단지인가요")
- `상담`: **판단을 요구합니다.** 특정 단지·시기·개인 사정에 대한 의견을 묻습니다.
  ("지금 사도 될까요", "○○단지 어떤가요", "저는 이런 상황인데 어떻게 할까요",
   "전세 낀 매물인데 괜찮을까요")
- `부정`: 반박·비판·시비·비아냥

애매하면 **`상담` 으로 분류하세요.** 잘못 자동 답변하는 것보다
사람에게 넘기는 쪽이 낫습니다.

## 답글 초안 (`인사`, `사실질문` 에만 씁니다)

- 존댓말. 상대가 반말이어도 존댓말로 답합니다
- **1~2문장.** 짧게
- 이모티콘과 물결(~)을 쓰지 않습니다
- '~인 것 같습니다', '~로 보여집니다' 를 쓰지 않습니다
- **원글에 없는 숫자·기한·요건을 쓰지 마세요.** 이건 특히 엄격합니다.
  용어를 묻는 질문에는 뜻만 풀어 쓰고, 법정 비율·횟수·기간은 붙이지 마세요.
  ("계약갱신요구권이 뭔가요" → 세입자가 계약 연장을 요구할 수 있는 권리라고만
   씁니다. "1회", "5%" 같은 수치는 넣지 않습니다)
  틀린 법정 수치 하나가 공인중개사 계정의 신뢰를 깎습니다
- 근거가 없으면 답글을 비우고 분류를 `상담` 으로 바꾸세요
- 전망·추천·판단을 쓰지 마세요. 그건 계정 주인의 몫입니다
- 상담을 유도하는 영업 문구를 넣지 마세요

## `인사` 답글의 추가 제약 — 반드시 지키세요

받아주는 말만 씁니다. **단지·동네·시세에 대한 사실이나 평가를 덧붙이지 마세요.**
계정 주인이 직접 가서 본 것처럼 들리는 문장은 특히 안 됩니다.

  "여기 은근히 조용하고 좋죠"
  나쁨: 맞습니다. 직접 가보면 단지 주변이 생각보다 훨씬 쾌적하고 조용한 편입니다.
        (계정 주인이 확인해준 말이 됩니다. AI 는 그 단지를 모릅니다)
  좋음: 그렇게 봐주셔서 감사합니다.

  "아스테리움도 포함이죠"
  좋음: 짚어주셔서 감사합니다. 다음에 함께 살펴보겠습니다.

한 문장이면 충분합니다."""

PROMPT = """원글:
{post}

달린 댓글:
작성자: {username}
내용: {text}

JSON 으로만 답하세요.

{{
  "kind": "인사 | 사실질문 | 상담 | 부정",
  "reply": "<'인사'·'사실질문' 일 때만 답글 1~2문장. 나머지는 빈 문자열>",
  "why": "<왜 그렇게 분류했는지 한 문장>"
}}"""


def classify(reply: dict, post: str) -> dict:
    d = ask_json(
        SYSTEM,
        PROMPT.format(post=post[:1200] or "(원글을 가져오지 못했습니다)",
                      username=reply.get("username", "?"),
                      text=reply.get("text", "")),
        effort="medium",
    )
    kind = str(d.get("kind", "")).strip()
    text = str(d.get("reply", "")).strip()

    if kind not in AUTO_KINDS | HUMAN_KINDS:
        # 분류를 못 알아들으면 사람에게 넘긴다. 자동 답글의 기본값은 '안 함' 이다.
        print(f"[replies] 알 수 없는 분류 '{kind}' — 상담으로 넘깁니다", file=sys.stderr)
        kind, text = "상담", ""
    if kind in HUMAN_KINDS:
        text = ""
    if kind in AUTO_KINDS and not text:
        # 근거가 없어 답글을 비웠다는 뜻이다. 그러면 자동으로 나가면 안 된다.
        kind = "상담"

    return {"kind": kind, "reply": text, "why": str(d.get("why", "")).strip()}


def run() -> int:
    """스케줄이 하루 몇 번 부른다."""
    dry_run = os.environ.get("DRY_RUN", "0").strip().lower() in {"1", "true", "yes", "on"}
    # 기본값은 '자동 답글 안 함'. 초안만 만들어 카카오톡으로 보낸다.
    # 며칠 보고 납득되면 리포 변수 REPLY_AUTO 를 1 로 바꿔 켠다.
    auto = os.environ.get("REPLY_AUTO", "0").strip().lower() in {"1", "true", "yes", "on"}
    print(f"=== 댓글 확인 (DRY_RUN={dry_run} / 자동답글={'켜짐' if auto else '꺼짐'}) ===")

    handled = state_mod.load_replies()
    posts = recent_posts()
    print(f"[replies] 최근 {LOOKBACK_DAYS}일 글 {len(posts)}건 확인")

    items: list[dict] = []
    본문: dict[str, str] = {}
    for post in posts:
        새것 = [r for r in fetch_replies(post["id"]) if r["id"] not in handled]
        if 새것:
            본문[post["id"]] = post.get("text", "")
            items.extend(새것)

    print(f"[replies] 새 댓글 {len(items)}건")
    if not items:
        return 0

    replied, for_human, drafts = 0, [], []

    for item in items:
        root = item["root_post_id"]
        try:
            d = classify(item, 본문.get(root, ""))
        except Exception as e:
            print(f"[replies] 분류 실패 — 건너뜁니다: {e}", file=sys.stderr)
            continue

        who = item.get("username", "?")
        print(f"  [{d['kind']}] @{who}: {item['text'][:40]}")
        if d["reply"]:
            print(f"      → {d['reply']}")

        if d["kind"] in HUMAN_KINDS:
            for_human.append((who, item["text"], d["kind"]))
            # 사람이 답할 것은 처리 완료로 적지 않는다. 다음 실행 때 또 알리면
            # 시끄러우므로 '알림 보냄' 으로만 표시한다.
            handled = state_mod.mark_reply(handled, item["id"],
                                           kind=d["kind"], action="사람에게")
            continue

        if not auto or dry_run:
            drafts.append((who, item["text"], d["reply"]))
            continue

        try:
            publish_reply(d["reply"][:500], item["id"])
            handled = state_mod.mark_reply(handled, item["id"],
                                           kind=d["kind"], action="자동답글")
            replied += 1
        except Exception as e:
            print(f"[replies] 답글 실패 @{who}: {e}", file=sys.stderr)

    state_mod.save_replies(handled)

    if for_human:
        notify.needs_you(for_human)
    if drafts:
        notify.reply_drafts(drafts)

    print(f"[replies] 자동 답글 {replied}건 / 회원님 몫 {len(for_human)}건 "
          f"/ 초안만 {len(drafts)}건")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(run())
    except PublishError as e:
        print(f"[replies] 오류: {e}", file=sys.stderr)
        notify.failed("댓글 답글", str(e))
        sys.exit(1)
