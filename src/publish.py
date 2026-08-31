"""Threads 발행.

Threads API 는 로컬 파일 업로드를 받지 않는다. 이미지를 공개 URL 로 넘겨야 하므로
카드를 리포에 커밋하고 raw.githubusercontent.com URL 을 사용한다.

발행은 2단계다: 미디어 컨테이너 생성 → (처리 대기) → 발행.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import requests

API = "https://graph.threads.net/v1.0"


class PublishError(RuntimeError):
    pass


def _creds() -> tuple[str, str]:
    token = os.environ.get("THREADS_ACCESS_TOKEN")
    user_id = os.environ.get("THREADS_USER_ID")
    if not token or not user_id:
        raise PublishError("THREADS_ACCESS_TOKEN / THREADS_USER_ID 가 설정되지 않았습니다.")
    return token, user_id


def raw_url_for(path: str) -> str:
    """리포에 커밋된 파일의 공개 raw URL. Actions 환경변수를 쓴다."""
    repo = os.environ.get("GITHUB_REPOSITORY")
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    base = os.environ.get("PUBLIC_IMAGE_BASE")
    rel = path.lstrip("./")
    if base:
        return f"{base.rstrip('/')}/{rel}"
    if not repo:
        raise PublishError(
            "이미지 공개 URL 을 만들 수 없습니다. GITHUB_REPOSITORY 또는 "
            "PUBLIC_IMAGE_BASE 를 설정하세요."
        )
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{rel}"


def commit_and_push(paths: list[str], message: str) -> None:
    """카드 이미지와 상태 파일을 커밋한다. 발행 전에 이미지가 공개돼 있어야 한다."""
    subprocess.run(["git", "add", "--", *paths], check=True)
    result = subprocess.run(["git", "diff", "--cached", "--quiet"])
    if result.returncode == 0:
        print("[publish] 커밋할 변경 없음")
        return
    subprocess.run(["git", "commit", "-m", message], check=True)
    subprocess.run(["git", "push"], check=True)
    print(f"[publish] 커밋·푸시 완료: {', '.join(paths)}")


def _wait_ready(container_id: str, token: str, timeout: int = 120) -> None:
    """컨테이너가 FINISHED 가 될 때까지 기다린다. 바로 발행하면 실패한다."""
    deadline = time.time() + timeout
    delay = 3
    while time.time() < deadline:
        r = requests.get(
            f"{API}/{container_id}",
            params={"fields": "status,error_message", "access_token": token},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        status = data.get("status")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise PublishError(f"컨테이너 처리 실패: {data.get('error_message')}")
        print(f"[publish] 컨테이너 상태 {status} — {delay}초 후 재확인")
        time.sleep(delay)
        delay = min(delay * 2, 20)
    raise PublishError("컨테이너 처리 대기 시간 초과")


def publish_image_post(text: str, image_url: str) -> str:
    token, user_id = _creds()

    r = requests.post(
        f"{API}/{user_id}/threads",
        data={
            "media_type": "IMAGE",
            "image_url": image_url,
            "text": text,
            "access_token": token,
        },
        timeout=30,
    )
    if not r.ok:
        raise PublishError(f"컨테이너 생성 실패 ({r.status_code}): {r.text}")
    container_id = r.json().get("id")
    if not container_id:
        raise PublishError(f"컨테이너 ID 를 받지 못했습니다: {r.text}")
    print(f"[publish] 컨테이너 생성 {container_id}")

    _wait_ready(container_id, token)

    r = requests.post(
        f"{API}/{user_id}/threads_publish",
        data={"creation_id": container_id, "access_token": token},
        timeout=30,
    )
    if not r.ok:
        raise PublishError(f"발행 실패 ({r.status_code}): {r.text}")
    post_id = r.json().get("id")
    print(f"[publish] 발행 완료 post_id={post_id}")
    return post_id


def refresh_token() -> str:
    """장기 토큰 갱신. 방치하면 60일 뒤 파이프라인이 조용히 죽는다."""
    token, _ = _creds()
    r = requests.get(
        "https://graph.threads.net/refresh_access_token",
        params={"grant_type": "th_refresh_token", "access_token": token},
        timeout=30,
    )
    if not r.ok:
        raise PublishError(f"토큰 갱신 실패 ({r.status_code}): {r.text}")
    data = r.json()
    new_token = data.get("access_token")
    if not new_token:
        raise PublishError(f"갱신 응답에 토큰이 없습니다: {r.text}")
    print(f"[publish] 토큰 갱신 완료 (만료까지 {data.get('expires_in')}초)")
    return new_token


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "refresh":
        print(refresh_token())
    else:
        print("사용법: python -m src.publish refresh")
