"""인스타그램 발행 — 공식 API(Instagram API with Instagram Login).

2026-10-16 결정. 브라우저 자동화로 인스타를 만졌더니 "사람인지 확인" 이 떴다
(10-11 경쟁 계정 100여 개 연속 조회 뒤). 공식 API 는 인스타가 허락한 길이라
차단 걱정이 없다. 스레드와 같은 방식이다.

- 호스트는 graph.instagram.com, 토큰은 인스타 사용자 토큰(약 60일, 갱신 가능)
- 이미지는 공개 URL 로만 받는다 → 스레드 카드처럼 리포에 커밋하고 raw URL 을 쓴다
- 발행은 2단계: 컨테이너 생성 → (처리 대기) → media_publish
- 프로필 수정(소개·고정·링크)은 API 로 안 된다. 그건 서프로님이 휴대폰에서 한다

**공개 게시는 서프로님이 그때그때 승인한 것만 올린다.** 이 모듈에 예약 실행은 없다.
"""
from __future__ import annotations

import os
import sys
import time

import requests

from .publish import raw_url_for, wait_url_ready

API = "https://graph.instagram.com/v23.0"


class InstagramError(RuntimeError):
    pass


def _creds() -> tuple[str, str]:
    token = os.environ.get("IG_ACCESS_TOKEN")
    user_id = os.environ.get("IG_USER_ID")
    if not token or not user_id:
        raise InstagramError("IG_ACCESS_TOKEN / IG_USER_ID 가 설정되지 않았습니다. "
                             "tools/save_instagram_token.py 를 먼저 실행하세요.")
    return token, user_id


def _post(path: str, data: dict) -> dict:
    r = requests.post(f"{API}/{path}", data=data, timeout=60)
    if not r.ok:
        raise InstagramError(f"{path} 실패 ({r.status_code}): {r.text[:500]}")
    return r.json()


def _wait_finished(container_id: str, token: str, timeout: int = 180) -> None:
    """컨테이너가 FINISHED 가 될 때까지 기다린다. 릴스는 수십 초 걸린다."""
    end = time.time() + timeout
    while time.time() < end:
        r = requests.get(f"{API}/{container_id}",
                         params={"fields": "status_code", "access_token": token},
                         timeout=30)
        status = r.json().get("status_code") if r.ok else None
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise InstagramError(f"컨테이너 처리 실패: {status} ({container_id})")
        time.sleep(5)
    raise InstagramError(f"컨테이너 처리 시간 초과 ({container_id})")


def _publish(container_id: str, token: str, user_id: str) -> str:
    _wait_finished(container_id, token)
    media_id = _post(f"{user_id}/media_publish",
                     {"creation_id": container_id, "access_token": token})["id"]
    print(f"[instagram] 발행 완료 media_id={media_id}")
    return media_id


def publish_image(image_url: str, caption: str) -> str:
    token, user_id = _creds()
    wait_url_ready(image_url)
    cid = _post(f"{user_id}/media",
                {"image_url": image_url, "caption": caption, "access_token": token})["id"]
    return _publish(cid, token, user_id)


def publish_carousel(image_urls: list[str], caption: str) -> str:
    """넘겨보는 카드(2~10장). 순서대로 올라간다."""
    if not 2 <= len(image_urls) <= 10:
        raise InstagramError(f"캐러셀은 2~10장이어야 합니다 (지금 {len(image_urls)}장)")
    token, user_id = _creds()
    children = []
    for url in image_urls:
        wait_url_ready(url)
        children.append(_post(f"{user_id}/media", {
            "image_url": url, "is_carousel_item": "true", "access_token": token,
        })["id"])
    for c in children:
        _wait_finished(c, token)
    cid = _post(f"{user_id}/media", {
        "media_type": "CAROUSEL", "children": ",".join(children),
        "caption": caption, "access_token": token,
    })["id"]
    return _publish(cid, token, user_id)


def permalink(media_id: str) -> str:
    token, _ = _creds()
    r = requests.get(f"{API}/{media_id}",
                     params={"fields": "permalink", "access_token": token}, timeout=30)
    return r.json().get("permalink", "") if r.ok else ""


def refresh_token() -> str:
    """장기 토큰 갱신. 발급 후 24시간이 지나야 갱신된다. 방치하면 60일 뒤 끊긴다."""
    token, _ = _creds()
    r = requests.get("https://graph.instagram.com/refresh_access_token",
                     params={"grant_type": "ig_refresh_token", "access_token": token},
                     timeout=30)
    if not r.ok:
        raise InstagramError(f"토큰 갱신 실패 ({r.status_code}): {r.text[:300]}")
    new = r.json().get("access_token")
    if not new:
        raise InstagramError(f"갱신 응답에 토큰이 없습니다: {r.text[:300]}")
    print(f"[instagram] 토큰 갱신 완료 (만료까지 {r.json().get('expires_in')}초)",
          file=sys.stderr)
    return new


def main(argv: list[str]) -> int:
    """
    사용법:
      python -m src.instagram refresh
      python -m src.instagram post <글.txt> <이미지1> [이미지2 ...]
        이미지는 리포에 커밋·푸시된 파일 경로(공개 raw URL 로 넘긴다)
    """
    if len(argv) >= 1 and argv[0] == "refresh":
        print(refresh_token())
        return 0
    if len(argv) >= 3 and argv[0] == "post":
        caption = open(argv[1], encoding="utf-8").read().strip()
        urls = [raw_url_for(p) for p in argv[2:]]
        mid = publish_carousel(urls, caption) if len(urls) > 1 else publish_image(urls[0], caption)
        print(permalink(mid) or mid)
        return 0
    print(main.__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
