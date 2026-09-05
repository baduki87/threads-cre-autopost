"""준비 상태 점검.

키를 하나씩 확인하고, 있으면 실제로 연결해본다.
설정하다 막혔을 때 무엇이 문제인지 바로 알 수 있게 하는 것이 목적이다.

사용법:  ./.venv/bin/python tools/check_setup.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# src 를 임포트해야 .env 가 환경변수로 올라온다 (src/__init__.py).
# 아래 점검들이 os.environ 을 바로 읽으므로 여기서 먼저 불러야 한다.
import src  # noqa: E402,F401

OK = "✅"
NO = "❌"
SKIP = "⏭️"

results: list[tuple[str, bool]] = []


def report(name: str, ok: bool, detail: str) -> None:
    mark = OK if ok else NO
    print(f"{mark} {name}\n   {detail}\n")
    results.append((name, ok))


def check_molit() -> None:
    """키가 필요 없는 소스. 항상 확인 가능하다."""
    from src.collect import fetch_molit

    try:
        items = fetch_molit(5)
    except Exception as e:
        report("국토교통부 보도자료", False, f"수집 실패: {e}")
        return
    if not items:
        report("국토교통부 보도자료", False, "연결은 됐지만 0건입니다. RSS 주소가 바뀌었을 수 있습니다.")
        return
    report("국토교통부 보도자료", True, f"{len(items)}건 수집 — 최신: {items[0].title[:40]}")


def check_naver() -> None:
    cid = os.environ.get("NAVER_CLIENT_ID")
    csec = os.environ.get("NAVER_CLIENT_SECRET")
    if not cid or not csec:
        print(f"{SKIP} 네이버 뉴스 검색\n   NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 미설정 (아직 발급 전)\n")
        return

    import requests

    try:
        r = requests.get(
            "https://openapi.naver.com/v1/search/news.json",
            headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": csec},
            params={"query": "상업용 부동산", "display": 3},
            timeout=15,
        )
    except requests.RequestException as e:
        report("네이버 뉴스 검색", False, f"연결 실패: {e}")
        return
    if r.status_code == 401:
        report("네이버 뉴스 검색", False, "인증 실패(401). 키를 다시 확인하세요.")
        return
    if not r.ok:
        report("네이버 뉴스 검색", False, f"HTTP {r.status_code}: {r.text[:120]}")
        return
    n = len(r.json().get("items", []))
    report("네이버 뉴스 검색", True, f"검색 정상 — '상업용 부동산' {n}건")


def check_llm() -> None:
    """무료(Gemini) 또는 유료(Claude) 중 설정된 쪽을 확인한다."""
    from src import llm

    has_gemini = bool(os.environ.get("GEMINI_API_KEY"))
    has_claude = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if not has_gemini and not has_claude:
        print(
            f"{SKIP} 글 생성 AI\n"
            "   GEMINI_API_KEY(무료) 또는 ANTHROPIC_API_KEY(유료) 중 하나가 필요합니다.\n"
        )
        return

    which = llm.provider()

    if which == "gemini":
        try:
            models = llm.list_gemini_models()
        except Exception as e:
            report("글 생성 AI (Gemini)", False, f"모델 조회 실패: {str(e)[:150]}")
            return
        try:
            chosen = llm.resolve_gemini_model()
            out = llm.ask_json("당신은 테스트 응답기입니다.",
                               '{"ok": true} 형태의 JSON 만 출력하세요.')
        except Exception as e:
            report("글 생성 AI (Gemini)", False, f"호출 실패: {str(e)[:200]}")
            return
        flash = [m for m in models if "flash" in m]
        report("글 생성 AI (Gemini · 무료)", True,
               f"모델 {chosen} 사용 / 호출 정상 (응답 {out}) — flash 계열 {len(flash)}종 사용 가능")
        return

    import anthropic

    try:
        out = llm.ask_json("당신은 테스트 응답기입니다.",
                           '{"ok": true} 형태의 JSON 만 출력하세요.')
    except anthropic.AuthenticationError:
        report("글 생성 AI (Claude)", False, "인증 실패. 키를 다시 확인하세요.")
        return
    except Exception as e:
        report("글 생성 AI (Claude)", False, f"호출 실패: {str(e)[:200]}")
        return
    report("글 생성 AI (Claude · 유료)", True, f"{llm.CLAUDE_MODEL} 호출 정상 (응답 {out})")


def check_threads() -> None:
    token = os.environ.get("THREADS_ACCESS_TOKEN")
    user_id = os.environ.get("THREADS_USER_ID")
    if not token or not user_id:
        print(f"{SKIP} Threads\n   THREADS_ACCESS_TOKEN / THREADS_USER_ID 미설정 (아직 발급 전)\n")
        return

    import requests

    try:
        r = requests.get(
            f"https://graph.threads.net/v1.0/{user_id}",
            params={"fields": "username", "access_token": token},
            timeout=20,
        )
    except requests.RequestException as e:
        report("Threads", False, f"연결 실패: {e}")
        return
    if not r.ok:
        report("Threads", False, f"HTTP {r.status_code}: {r.text[:200]}")
        return
    report("Threads", True, f"계정 연결 정상 — @{r.json().get('username')}")


def check_notion() -> None:
    """초안 승인과 메모 입력 창구. 없으면 발행 흐름이 돌지 않는다."""
    from src import notion

    if not notion.enabled():
        print(f"{SKIP} 노션\n   NOTION_TOKEN / NOTION_DB_ID 미설정 (아직 발급 전)\n")
        return
    ok, msg = notion.check()
    report("노션", ok, msg)


def check_kakao() -> None:
    """실패해도 조용히 지나가지 않게 해주는 장치. 없으면 놓치기 쉽다."""
    from src import notify

    if not notify.enabled():
        print(f"{SKIP} 카카오톡 알림\n"
              "   KAKAO_REST_API_KEY / KAKAO_REFRESH_TOKEN 미설정\n"
              "   설정하려면: ./.venv/bin/python tools/kakao_setup.py\n")
        return
    ok, msg = notify.check()
    report("카카오톡 알림", ok, msg)


def check_insights_scope() -> None:
    """성과 수집에는 threads_manage_insights 권한이 따로 필요하다."""
    token = os.environ.get("THREADS_ACCESS_TOKEN")
    user_id = os.environ.get("THREADS_USER_ID")
    if not token or not user_id:
        print(f"{SKIP} 성과 수집 권한\n   Threads 토큰 설정 후 확인할 수 있습니다\n")
        return

    import requests

    try:
        r = requests.get(
            f"https://graph.threads.net/v1.0/{user_id}/threads",
            params={"fields": "id", "limit": 1, "access_token": token},
            timeout=20,
        )
        if not r.ok:
            report("성과 수집 권한", False, f"HTTP {r.status_code}: {r.text[:150]}")
            return
        items = r.json().get("data", [])
        if not items:
            print(f"{SKIP} 성과 수집 권한\n   발행된 글이 없어 확인할 수 없습니다\n")
            return
        mid = items[0]["id"]
        r2 = requests.get(
            f"https://graph.threads.net/v1.0/{mid}/insights",
            params={"metric": "views,likes,replies", "access_token": token},
            timeout=20,
        )
    except requests.RequestException as e:
        report("성과 수집 권한", False, f"연결 실패: {e}")
        return

    if not r2.ok:
        report("성과 수집 권한", False,
               "threads_manage_insights 권한이 없습니다. 토큰을 다시 발급하세요.\n"
               f"   {r2.text[:150]}")
        return
    report("성과 수집 권한", True, "insights 조회 정상")


def check_font() -> None:
    from src.card import _load

    try:
        f = _load("bold", 40)
    except RuntimeError as e:
        report("한글 폰트", False, str(e))
        return
    report("한글 폰트", True, f"{f.getname()}")


def check_image_host() -> None:
    """Threads 는 공개 URL 로만 이미지를 받는다. 여기가 막히면 발행이 안 된다."""
    base = os.environ.get("PUBLIC_IMAGE_BASE")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if base:
        report("이미지 공개 URL", True, f"PUBLIC_IMAGE_BASE 사용: {base}")
        return
    if repo:
        report("이미지 공개 URL", True, f"리포 raw URL 사용: {repo} (공개 리포여야 합니다)")
        return
    print(
        f"{SKIP} 이미지 공개 URL\n"
        "   로컬에서는 확인할 수 없습니다. GitHub Actions 에서 자동 설정되거나,\n"
        "   PUBLIC_IMAGE_BASE 로 직접 지정합니다. 리포가 비공개면 발행이 실패합니다.\n"
    )


def check_misplaced_keys() -> None:
    """키를 엉뚱한 칸에 넣는 실수를 잡는다.

    .env 의 항목들이 붙어 있어서 실제로 자주 헷갈린다.
    토큰마다 접두사가 달라 형식으로 구분할 수 있다.
    """
    # 각 서비스 토큰을 알아보는 표식.
    # "이 칸에 이게 있어야 한다"가 아니라 "이건 저 서비스 것이다"로만 쓴다.
    # 형식은 서비스가 언제든 바꾸므로(Gemini 는 AIza → AQ. 로 바뀌었다)
    # 잘못된 자리에 있는 게 확실할 때만 지적한다.
    signatures = {
        "NOTION_TOKEN": ("ntn_", "secret_"),
        "ANTHROPIC_API_KEY": ("sk-ant-",),
        "GEMINI_API_KEY": ("AIza", "AQ."),
    }
    problems = []
    for slot in ("NOTION_TOKEN", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
                 "THREADS_ACCESS_TOKEN", "KAKAO_REFRESH_TOKEN"):
        value = os.environ.get(slot, "")
        if not value:
            continue
        for owner, marks in signatures.items():
            if owner != slot and value.startswith(marks):
                problems.append(f"{slot} 에 {owner} 값이 들어가 있습니다")
                break

    if problems:
        report("키 배치", False, "\n   ".join(problems) + "\n   .env 를 열어 바로잡으세요")
    elif any(os.environ.get(k) for k in signatures):
        report("키 배치", True, "각 키가 알맞은 칸에 있습니다")


if __name__ == "__main__":
    print("=" * 56)
    print(" 준비 상태 점검")
    print("=" * 56 + "\n")

    check_misplaced_keys()

    check_font()
    check_molit()
    check_naver()
    check_llm()
    check_threads()
    check_notion()
    check_kakao()
    check_insights_scope()
    check_image_host()

    failed = [n for n, ok in results if not ok]
    print("=" * 56)
    if failed:
        print(f"확인 필요: {', '.join(failed)}")
        sys.exit(1)
    print("점검한 항목은 모두 정상입니다. (⏭️ 는 아직 발급 전이라 건너뛴 항목)")
