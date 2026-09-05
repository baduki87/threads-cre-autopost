"""Threads 토큰 저장 도우미.

토큰을 붙여넣으면 .env 에 저장하고, 계정 ID 까지 자동으로 알아내
THREADS_USER_ID 와 THREADS_ACCOUNT_HANDLE 도 함께 채운다.

토큰은 화면에 표시되지 않는다 (getpass).

사용법:  ./.venv/bin/python tools/save_threads_token.py
"""
from __future__ import annotations

import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src  # noqa: E402,F401  (.env 로드)
import requests  # noqa: E402

ENV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
)
API = "https://graph.threads.net/v1.0"


def save_env(pairs: dict[str, str]) -> None:
    """해당 줄만 갈아끼우고 나머지는 그대로 둔다."""
    lines = open(ENV_PATH, encoding="utf-8").read().splitlines() \
        if os.path.exists(ENV_PATH) else []
    remaining = dict(pairs)
    out = []
    for ln in lines:
        key = ln.split("=", 1)[0] if "=" in ln else ""
        if key in remaining:
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(ln)
    for key, value in remaining.items():
        out.append(f"{key}={value}")
    open(ENV_PATH, "w", encoding="utf-8").write("\n".join(out) + "\n")


def main() -> int:
    print("""
============================================================
 Threads 토큰 저장
============================================================
 메타 개발자 사이트에서 [복사] 버튼으로 복사한 토큰을
 아래에 붙여넣고 엔터를 누르세요. (⌘V)

 보안을 위해 입력한 내용은 화면에 보이지 않습니다.
 붙여넣고 그냥 엔터만 치시면 됩니다.
------------------------------------------------------------""")

    token = getpass.getpass("토큰 붙여넣기: ").strip()
    if not token:
        print("\n토큰이 비어 있습니다. 다시 실행해주세요.")
        return 1
    if len(token) < 50:
        print(f"\n토큰이 너무 짧습니다 ({len(token)}자). 전체를 복사했는지 확인해주세요.")
        return 1

    print(f"\n토큰 {len(token)}자를 받았습니다. 계정을 확인하는 중…")

    try:
        r = requests.get(
            f"{API}/me",
            params={"fields": "id,username", "access_token": token},
            timeout=20,
        )
    except requests.RequestException as e:
        print(f"연결 실패: {e}")
        return 1

    if not r.ok:
        print(f"\n토큰이 거부됐습니다 ({r.status_code}):\n{r.text[:300]}")
        print("\n메타 사이트에서 토큰을 다시 생성해보세요.")
        return 1

    data = r.json()
    user_id = data.get("id", "")
    username = data.get("username", "")
    if not user_id:
        print(f"\n계정 ID 를 받지 못했습니다: {r.text[:200]}")
        return 1

    save_env({
        "THREADS_ACCESS_TOKEN": token,
        "THREADS_USER_ID": user_id,
        "THREADS_ACCOUNT_HANDLE": f"@{username}" if username else "",
    })

    print(f"""
============================================================
 저장 완료
============================================================
 계정      @{username}
 USER_ID   {user_id}

 .env 에 아래 세 항목을 넣었습니다.
   THREADS_ACCESS_TOKEN
   THREADS_USER_ID
   THREADS_ACCOUNT_HANDLE

 이제 전체 점검을 돌려보세요.

   ./.venv/bin/python tools/check_setup.py
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
