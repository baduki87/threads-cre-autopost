"""카카오톡 알림 설정 — 브라우저가 알아서 돌아옵니다.

카카오 토큰을 받으려면 브라우저에서 동의하고 '인가 코드'를 받아야 하는데,
보통은 주소창을 복사해 붙여넣어야 한다. 그게 제일 헷갈리는 부분이라
이 스크립트가 잠깐 작은 서버를 띄워 코드를 직접 받아낸다.

회원님이 하실 일은 브라우저에서 **동의 버튼을 누르는 것**뿐이다.
받은 토큰은 .env 에 자동으로 저장된다.

사용법:  ./.venv/bin/python tools/kakao_setup.py
"""
from __future__ import annotations

import http.server
import os
import socket
import sys
import urllib.parse
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

PORT = 8765
REDIRECT_URI = f"http://localhost:{PORT}/oauth"
AUTH_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"
ENV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
)

GUIDE = f"""
============================================================
 카카오톡 알림 설정
============================================================

카카오 개발자 사이트에서 앱을 만들어야 합니다. (5분)
이미 하셨으면 엔터만 누르고 넘어가세요.

 1) https://developers.kakao.com/console/app  접속 → 카카오 로그인
 2) [애플리케이션 추가하기]
       앱 이름  : 스레드자동발행
       회사명   : 아무거나 (본인 이름도 됩니다)

 3) 만든 앱 클릭 → 왼쪽 [앱 키]
       ★ REST API 키를 복사해 두세요

 4) 왼쪽 [카카오 로그인]
       활성화 설정을 ON
       Redirect URI 에 아래 주소를 **그대로** 등록하세요

           {REDIRECT_URI}

 5) 왼쪽 [카카오 로그인] → [동의항목]
       '카카오톡 메시지 전송' 을 찾아 [설정] → 선택 동의
       (이게 없으면 메시지가 안 갑니다)

------------------------------------------------------------
"""

DONE_PAGE = """<!doctype html><meta charset="utf-8">
<title>연결 완료</title>
<style>
 body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;
      display:flex;align-items:center;justify-content:center;
      height:100vh;margin:0;background:#f7f7f5;color:#37352f}
 .box{text-align:center;padding:40px 56px;background:#fff;
      border-radius:12px;box-shadow:0 2px 16px rgba(0,0,0,.08)}
 h1{font-size:20px;margin:0 0 8px}
 p{color:#787774;margin:0;font-size:14px}
</style>
<div class="box">
  <h1>연결됐습니다</h1>
  <p>이 창은 닫으셔도 됩니다. 터미널로 돌아가세요.</p>
</div>"""


class _Catcher(http.server.BaseHTTPRequestHandler):
    """리다이렉트로 돌아온 인가 코드를 받아낸다."""

    code: str | None = None
    error: str | None = None

    def do_GET(self) -> None:  # noqa: N802
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        _Catcher.code = params.get("code", [None])[0]
        _Catcher.error = params.get("error_description", params.get("error", [None]))[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(DONE_PAGE.encode("utf-8"))

    def log_message(self, *args) -> None:   # 서버 로그를 화면에 뿌리지 않는다
        pass


def _port_free() -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", PORT)) != 0


def _save_env(pairs: dict[str, str]) -> bool:
    """.env 의 해당 줄만 갈아끼운다. 나머지 줄은 건드리지 않는다."""
    if not os.path.exists(ENV_PATH):
        return False
    lines = open(ENV_PATH, encoding="utf-8").read().splitlines()
    remaining = dict(pairs)
    out = []
    for ln in lines:
        key = ln.split("=", 1)[0] if "=" in ln else ""
        if key in remaining:
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(ln)
    for key, value in remaining.items():      # 없던 항목은 뒤에 붙인다
        out.append(f"{key}={value}")
    open(ENV_PATH, "w", encoding="utf-8").write("\n".join(out) + "\n")
    return True


def main() -> int:
    print(GUIDE)

    if not _port_free():
        print(f"{PORT} 번 포트를 이미 쓰고 있습니다.\n"
              "다른 프로그램을 끄고 다시 실행하거나, 저에게 알려주세요.")
        return 1

    rest_key = (os.environ.get("KAKAO_REST_API_KEY") or "").strip()
    if rest_key:
        print(f"이미 저장된 REST API 키를 씁니다 ({rest_key[:6]}…)")
        print("다른 키를 쓰시려면 새로 붙여넣고, 그대로면 엔터만 누르세요.")
        typed = input("REST API 키 [엔터=그대로]: ").strip()
        if typed:
            rest_key = typed
    else:
        rest_key = input("3번에서 복사한 REST API 키를 붙여넣고 엔터: ").strip()

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

    server = http.server.HTTPServer(("127.0.0.1", PORT), _Catcher)
    server.timeout = 1      # 1초씩 끊어 기다리며 취소 가능하게 한다

    print(f"""
------------------------------------------------------------
 브라우저를 엽니다. **[동의하고 계속하기]** 를 눌러주세요.

 복사·붙여넣기는 필요 없습니다. 동의만 하시면 이 창으로 돌아옵니다.

 브라우저가 자동으로 안 열리면 아래 주소를 직접 여세요.

 {auth_link}
------------------------------------------------------------
""")
    webbrowser.open(auth_link)
    print("기다리는 중… (최대 3분)")

    waited = 0
    while _Catcher.code is None and _Catcher.error is None and waited < 180:
        server.handle_request()      # timeout=1 이라 1초씩 끊어서 기다린다
        waited += 1
    server.server_close()

    if _Catcher.error:
        print(f"\n동의 과정에서 거절되었거나 오류가 났습니다: {_Catcher.error}")
        print("5번 [동의항목]에서 '카카오톡 메시지 전송'이 켜져 있는지 확인해주세요.")
        return 1
    if not _Catcher.code:
        print("\n3분 안에 동의가 확인되지 않았습니다. 다시 실행해주세요.")
        return 1

    print("동의를 확인했습니다. 토큰을 받는 중…")
    r = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": rest_key,
            "redirect_uri": REDIRECT_URI,
            "code": _Catcher.code,
        },
        timeout=20,
    )
    if not r.ok:
        print(f"\n토큰 발급 실패 ({r.status_code}): {r.text[:300]}")
        print("\n4번 Redirect URI 가 아래와 정확히 같은지 확인해주세요.")
        print(f"  {REDIRECT_URI}")
        return 1

    refresh = r.json().get("refresh_token")
    if not refresh:
        print(f"\n응답에 refresh_token 이 없습니다: {r.text[:300]}")
        return 1

    saved = _save_env({
        "KAKAO_REST_API_KEY": rest_key,
        "KAKAO_REFRESH_TOKEN": refresh,
    })

    print("\n" + "=" * 60)
    if saved:
        print(" .env 에 저장했습니다. 이제 테스트 메시지를 보냅니다.")
    else:
        print(" .env 파일이 없어 저장하지 못했습니다. 아래를 직접 넣으세요.\n")
        print(f"KAKAO_REST_API_KEY={rest_key}")
        print(f"KAKAO_REFRESH_TOKEN={refresh}")
    print("=" * 60 + "\n")

    os.environ["KAKAO_REST_API_KEY"] = rest_key
    os.environ["KAKAO_REFRESH_TOKEN"] = refresh
    from src import notify
    ok, msg = notify.check()
    print(("성공 — " if ok else "실패 — ") + msg)

    if ok:
        print("""
카카오톡 '나와의 채팅' 을 확인해보세요.

깃허브에도 등록하시면 매일 자동 실행될 때도 알림이 옵니다.

  gh secret set KAKAO_REST_API_KEY
  gh secret set KAKAO_REFRESH_TOKEN
""")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
