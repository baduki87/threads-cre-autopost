"""카카오톡 알림 설정 도우미.

카카오는 토큰 받는 절차가 번거롭다. 브라우저에서 로그인해 '인가 코드'를 받고
그걸 토큰으로 바꿔야 하는데, 이 스크립트가 그 과정을 대신 안내한다.

사용법:  ./.venv/bin/python tools/kakao_setup.py
"""
from __future__ import annotations

import os
import sys
import urllib.parse

import requests

REDIRECT_URI = "https://example.com/oauth"
AUTH_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"

GUIDE = f"""
============================================================
 카카오톡 알림 설정
============================================================

먼저 카카오 개발자 사이트에서 앱을 만들어야 합니다.
아직 안 만드셨으면 아래 순서대로 하세요. (5분)

 1) https://developers.kakao.com/console/app 접속 → 카카오 로그인
 2) [애플리케이션 추가하기]
      앱 이름     : 스레드자동발행
      회사명      : 아무거나 (본인 이름도 됩니다)
 3) 만든 앱 클릭 → 왼쪽 [앱 키] 메뉴
      **REST API 키**를 복사해 두세요
 4) 왼쪽 [카카오 로그인] 메뉴
      활성화 설정을 **ON** 으로
      Redirect URI 에 아래 주소를 그대로 등록:

        {REDIRECT_URI}

 5) 왼쪽 [카카오 로그인] → [동의항목] 메뉴
      '카카오톡 메시지 전송' 을 찾아 **선택 동의** 로 설정
      (이게 없으면 메시지가 안 갑니다)

------------------------------------------------------------
"""


def main() -> int:
    print(GUIDE)

    rest_key = os.environ.get("KAKAO_REST_API_KEY") or input(
        "3번에서 복사한 REST API 키를 붙여넣고 엔터: "
    ).strip()
    if not rest_key:
        print("REST API 키가 필요합니다.")
        return 1

    params = urllib.parse.urlencode({
        "client_id": rest_key,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "talk_message",
    })
    auth_link = f"{AUTH_URL}?{params}"

    print(f"""
------------------------------------------------------------
 다음: 아래 주소를 브라우저에 붙여넣고 접속하세요.

{auth_link}

 카카오 로그인 후 '동의하고 계속하기' 를 누르면
 example.com 페이지로 넘어갑니다. 페이지 내용은 무시하고
 **브라우저 주소창 전체**를 복사하세요.

 주소가 이렇게 생겼습니다:
   https://example.com/oauth?code=abcd1234...
------------------------------------------------------------
""")

    pasted = input("복사한 주소를 붙여넣고 엔터: ").strip()
    if not pasted:
        print("주소가 비어 있습니다.")
        return 1

    # 주소 전체를 붙여넣어도 되고 코드만 붙여넣어도 되게 한다.
    if "code=" in pasted:
        query = urllib.parse.urlparse(pasted).query
        code = urllib.parse.parse_qs(query).get("code", [""])[0]
    else:
        code = pasted
    if not code:
        print("주소에서 code 를 찾지 못했습니다. 주소창 전체를 복사했는지 확인하세요.")
        return 1

    r = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": rest_key,
            "redirect_uri": REDIRECT_URI,
            "code": code,
        },
        timeout=20,
    )
    if not r.ok:
        print(f"\n토큰 발급 실패 ({r.status_code}): {r.text[:300]}")
        print("\n인가 코드는 한 번만 쓸 수 있고 몇 분이면 만료됩니다.")
        print("이 스크립트를 다시 실행해 새 주소로 받아보세요.")
        return 1

    data = r.json()
    refresh = data.get("refresh_token")
    if not refresh:
        print(f"\n응답에 refresh_token 이 없습니다: {r.text[:300]}")
        return 1

    print(f"""
============================================================
 발급 완료
============================================================

.env 파일에 아래 두 줄을 넣으세요.  (open -e .env)

KAKAO_REST_API_KEY={rest_key}
KAKAO_REFRESH_TOKEN={refresh}

깃허브에도 같이 등록하세요.

  gh secret set KAKAO_REST_API_KEY
  gh secret set KAKAO_REFRESH_TOKEN

넣은 뒤 아래로 확인하면 카카오톡으로 테스트 메시지가 옵니다.

  ./.venv/bin/python -m src.notify
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
