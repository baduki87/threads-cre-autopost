"""인스타그램 토큰 저장 도우미.

메타 개발자 사이트에서 복사한 토큰을 붙여넣으면
  1) 어느 계정의 토큰인지 확인하고(@pro_konwoo 여야 한다)
  2) 로컬 .env 에 IG_ACCESS_TOKEN / IG_USER_ID 를 넣고
  3) GitHub Actions 시크릿에도 같은 값을 넣는다(주 1회 자동 갱신용)

토큰은 화면에 표시되지 않는다 (getpass). 명령줄 인자로도 받지 않는다.

사용법:  ./.venv/bin/python tools/save_instagram_token.py
"""
from __future__ import annotations

import getpass
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src  # noqa: E402,F401  (.env 로드)
import requests  # noqa: E402

from tools.save_threads_token import save_env  # noqa: E402

API = "https://graph.instagram.com/v23.0"
EXPECTED = "pro_konwoo"


def set_secret(name: str, value: str) -> bool:
    """값을 표준입력으로 넘긴다 — 명령줄에 남지 않게."""
    try:
        r = subprocess.run(["gh", "secret", "set", name], input=value,
                           text=True, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"  {name}: gh 실행 실패 ({e})")
        return False
    if r.returncode != 0:
        print(f"  {name}: 저장 실패 — {r.stderr.strip()[:200]}")
        return False
    print(f"  {name}: 저장됨")
    return True


def main() -> int:
    print("""
============================================================
 인스타그램 토큰 저장
============================================================
 메타 개발자 사이트에서 복사한 토큰을 붙여넣고 엔터 (⌘V)
 보안을 위해 입력한 내용은 화면에 보이지 않습니다.
------------------------------------------------------------""")
    token = getpass.getpass("토큰 붙여넣기: ").strip()
    if len(token) < 50:
        print(f"\n토큰이 비었거나 너무 짧습니다 ({len(token)}자). 전체를 복사했는지 확인해주세요.")
        return 1

    try:
        r = requests.get(f"{API}/me", params={"fields": "user_id,username",
                                               "access_token": token}, timeout=20)
    except requests.RequestException as e:
        print(f"연결 실패: {e}")
        return 1
    if not r.ok:
        print(f"\n토큰이 거부됐습니다 ({r.status_code}):\n{r.text[:300]}")
        return 1
    data = r.json()
    user_id, username = str(data.get("user_id", "")), data.get("username", "")
    if not user_id:
        print(f"\n계정 ID 를 받지 못했습니다: {r.text[:200]}")
        return 1
    if username != EXPECTED:
        print(f"\n⚠️ @{username} 계정의 토큰입니다. @{EXPECTED} 로 다시 만들어주세요. 저장하지 않았습니다.")
        return 1

    save_env({"IG_ACCESS_TOKEN": token, "IG_USER_ID": user_id})
    print(f"\n계정 @{username} 확인. 로컬 .env 에 저장했습니다.")
    print("GitHub 시크릿에도 저장합니다…")
    ok = set_secret("IG_ACCESS_TOKEN", token) & set_secret("IG_USER_ID", user_id)
    print("\n" + ("완료. 이제 Claude 에게 '했어' 라고 말씀하세요." if ok else
                  "로컬 저장은 됐지만 GitHub 시크릿 저장이 실패했습니다. Claude 에게 알려주세요."))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
