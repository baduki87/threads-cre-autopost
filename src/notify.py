"""카카오톡 '나에게 보내기' 알림.

초안이 올라왔을 때와 어딘가 실패했을 때 폰으로 알려준다.
알림이 없으면 실패해도 조용히 지나가고, 승인도 깜빡하게 된다.

토큰 구조가 두 겹이다.
  refresh_token  약 2개월. 시크릿에 저장한다
  access_token   약 6시간. 필요할 때마다 refresh 로 새로 받는다

access_token 을 저장하지 않고 매번 새로 받는 이유는, 저장해두면
만료 시각을 관리해야 하고 그게 조용히 죽는 원인이 되기 때문이다.

알림은 부가 기능이다. 여기서 나는 예외는 절대 파이프라인을 멈추지 않는다.
"""
from __future__ import annotations

import json
import os
import sys

import requests

AUTH = "https://kauth.kakao.com/oauth/token"
SEND = "https://kapi.kakao.com/v2/api/talk/memo/default/send"


def enabled() -> bool:
    return bool(os.environ.get("KAKAO_REST_API_KEY")
                and os.environ.get("KAKAO_REFRESH_TOKEN"))


def _access_token() -> tuple[str | None, str | None]:
    """(access_token, 새 refresh_token or None).

    카카오는 refresh_token 만료가 1개월 미만으로 남았을 때만 새 것을 준다.
    새로 받으면 시크릿을 갈아줘야 하므로 함께 돌려준다.
    """
    data = {
        "grant_type": "refresh_token",
        "client_id": os.environ["KAKAO_REST_API_KEY"],
        "refresh_token": os.environ["KAKAO_REFRESH_TOKEN"],
    }
    # 카카오는 REST 키 발급 시 클라이언트 시크릿을 기본 활성화한다.
    # 켜져 있으면 이 값 없이는 토큰이 발급되지 않는다.
    secret = os.environ.get("KAKAO_CLIENT_SECRET")
    if secret:
        data["client_secret"] = secret

    r = requests.post(AUTH, data=data, timeout=20)
    if not r.ok:
        print(f"[notify] 토큰 갱신 실패 ({r.status_code}): {r.text[:200]}", file=sys.stderr)
        return None, None
    data = r.json()
    return data.get("access_token"), data.get("refresh_token")


def send(text: str, link_url: str = "", button_title: str = "") -> bool:
    """나와의 채팅방으로 메시지 하나. 실패해도 예외를 던지지 않는다."""
    if not enabled():
        return False

    try:
        token, new_refresh = _access_token()
        if not token:
            return False
        if new_refresh:
            # 시크릿 교체가 필요하다. 로그에 남겨야 놓치지 않는다.
            print("[notify] 새 refresh_token 이 발급됐습니다. "
                  "KAKAO_REFRESH_TOKEN 시크릿을 갱신하세요.", file=sys.stderr)

        template = {
            "object_type": "text",
            "text": text[:400],          # 카카오 텍스트 템플릿 제한
            "link": {"web_url": link_url, "mobile_web_url": link_url} if link_url
                    else {"web_url": "https://www.threads.com"},
        }
        if link_url and button_title:
            template["button_title"] = button_title[:14]

        r = requests.post(
            SEND,
            headers={"Authorization": f"Bearer {token}"},
            data={"template_object": json.dumps(template, ensure_ascii=False)},
            timeout=20,
        )
        if not r.ok:
            hint = ""
            if "-402" in r.text:
                hint = " — talk_message 동의가 안 돼 있습니다. 재동의가 필요합니다."
            print(f"[notify] 전송 실패 ({r.status_code}): {r.text[:200]}{hint}",
                  file=sys.stderr)
            return False
        return True
    except Exception as e:     # 알림 때문에 파이프라인이 멈추면 안 된다
        print(f"[notify] 예외 발생 (무시하고 계속): {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------- 상황별

def draft_ready(title: str, text: str, notion_url: str = "") -> None:
    body = (
        "오늘 초안이 나왔습니다.\n\n"
        f"[{title}]\n\n"
        f"{text[:200]}{'…' if len(text) > 200 else ''}\n\n"
        "노션에서 확인하고 '승인'으로 바꾸면 밤 9시에 올라갑니다."
    )
    send(body, notion_url, "노션에서 확인")


def published(title: str, post_id: str, with_reply: bool) -> None:
    body = (
        f"발행 완료했습니다.\n\n[{title}]\n\n"
        + ("첫 댓글도 함께 달렸습니다." if with_reply else "첫 댓글은 없습니다.")
    )
    send(body, "https://www.threads.com/@pro_konwoo", "스레드에서 보기")


def failed(stage: str, detail: str) -> None:
    send(f"[{stage}] 단계에서 실패했습니다.\n\n{detail[:250]}\n\n"
         "오늘은 자동으로 올라가지 않습니다.")


def check() -> tuple[bool, str]:
    """준비 상태 점검용."""
    if not enabled():
        return False, "KAKAO_REST_API_KEY / KAKAO_REFRESH_TOKEN 미설정"
    token, _ = _access_token()
    if not token:
        return False, "토큰 갱신 실패 — refresh_token 이 만료됐을 수 있습니다"
    ok = send("스레드 자동화 알림 연결을 확인했습니다.")
    if not ok:
        return False, "토큰은 받았지만 메시지 전송에 실패했습니다 (talk_message 동의 확인)"
    return True, "카카오톡으로 테스트 메시지를 보냈습니다. 확인해보세요"


if __name__ == "__main__":
    ok, msg = check()
    print(("OK " if ok else "실패 ") + msg)
