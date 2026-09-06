"""네이버 검색 API 키 저장 도우미.

Client ID 와 Secret 을 붙여넣으면 .env 에 저장하고,
실제로 검색이 되는지 바로 확인한다.

사용법:  ./.venv/bin/python tools/save_naver_keys.py
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
SEARCH = "https://openapi.naver.com/v1/search/news.json"


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
 네이버 검색 API 키 저장
============================================================
 https://developers.naver.com/apps/#/register 에서 받은
 Client ID 와 Client Secret 을 차례로 붙여넣으세요.

 Client ID 는 화면에 보이고, Secret 은 가려집니다.
------------------------------------------------------------""")

    cid = input("Client ID: ").strip()
    if not cid:
        print("\nClient ID 가 비어 있습니다.")
        return 1

    csec = getpass.getpass("Client Secret (가려짐): ").strip()
    if not csec:
        print("\nClient Secret 이 비어 있습니다.")
        return 1

    print("\n검색이 되는지 확인하는 중…")
    try:
        r = requests.get(
            SEARCH,
            headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": csec},
            params={"query": "재건축 사업시행인가", "display": 3, "sort": "date"},
            timeout=20,
        )
    except requests.RequestException as e:
        print(f"연결 실패: {e}")
        return 1

    if r.status_code == 401:
        print("\n인증 실패(401). ID 나 Secret 이 잘못됐습니다.")
        return 1
    if r.status_code == 403:
        print("\n권한 없음(403). 애플리케이션에서 '검색' API 를 선택했는지 확인하세요.")
        return 1
    if not r.ok:
        print(f"\n실패 ({r.status_code}): {r.text[:300]}")
        return 1

    items = r.json().get("items", [])
    save_env({"NAVER_CLIENT_ID": cid, "NAVER_CLIENT_SECRET": csec})

    print(f"""
============================================================
 저장 완료 — 검색 정상 ({len(items)}건)
============================================================""")
    import re
    for it in items:
        title = re.sub(r"<[^>]+>", "", it.get("title", ""))
        print(f"  · {title[:60]}")

    print("""
 .env 에 저장했습니다. 이제 소재가 국토부 보도자료뿐이던 데서
 뉴스까지 넓어집니다.

 깃허브에도 등록하려면:
   gh secret set NAVER_CLIENT_ID
   gh secret set NAVER_CLIENT_SECRET
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
