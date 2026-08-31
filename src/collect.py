"""소스 수집: 국토교통부 보도자료(RSS) + 네이버 뉴스 검색 API."""
from __future__ import annotations

import html
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import feedparser
import requests
import yaml

from .models import Article

KST = timezone(timedelta(hours=9))
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)
MOLIT_RSS = "https://www.molit.go.kr/dev/board/board_rss.jsp?rss_id=NEWS"
NAVER_NEWS_API = "https://openapi.naver.com/v1/search/news.json"


def _session() -> requests.Session:
    """국토부는 첫 요청에 307 + TMOSHCooKie 를 내려주는 쿠키 챌린지를 건다.
    Session 이 쿠키를 물고 리다이렉트를 따라가야 본문을 받을 수 있다."""
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
    return s


def _get_with_retry(sess: requests.Session, url: str, *, tries: int = 3,
                    timeout: int = 25, **kwargs) -> requests.Response:
    """일시적인 연결 실패로 하루치 수집을 통째로 잃지 않도록 재시도한다.
    해외 리전에서 국내 사이트로 붙을 때 간헐적인 타임아웃이 실제로 발생한다."""
    last: Exception | None = None
    for attempt in range(1, tries + 1):
        try:
            resp = sess.get(url, timeout=timeout, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            last = e
            if attempt < tries:
                wait = 2 ** attempt
                print(f"[collect] {url} 실패({attempt}/{tries}) — {wait}초 후 재시도", file=sys.stderr)
                time.sleep(wait)
    raise last  # type: ignore[misc]


def _strip_tags(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def fetch_molit(limit: int = 15) -> list[Article]:
    sess = _session()
    try:
        resp = _get_with_retry(sess, MOLIT_RSS)
    except requests.RequestException as e:
        print(f"[collect] 국토부 RSS 최종 실패: {e}", file=sys.stderr)
        return []

    feed = feedparser.parse(resp.content)
    out: list[Article] = []
    for entry in feed.entries[:limit]:
        published = None
        if getattr(entry, "published_parsed", None):
            # feedparser 는 published_parsed 를 UTC 로 정규화한다. KST 로 붙이면 9시간 어긋난다.
            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        out.append(
            Article(
                title=_strip_tags(entry.get("title", "")),
                url=entry.get("link", ""),
                source="국토교통부",
                kind="policy",
                published_at=published,
                snippet=_strip_tags(entry.get("description", ""))[:500],
            )
        )
    return [a for a in out if a.title and a.url]


def fetch_naver_news(keywords: list[str], per_keyword: int = 10) -> list[Article]:
    cid = os.environ.get("NAVER_CLIENT_ID")
    csec = os.environ.get("NAVER_CLIENT_SECRET")
    if not cid or not csec:
        print("[collect] NAVER_CLIENT_ID/SECRET 미설정 — 뉴스 수집 건너뜀", file=sys.stderr)
        return []

    headers = {"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": csec}
    sess = _session()
    out: list[Article] = []
    for kw in keywords:
        try:
            r = _get_with_retry(
                sess,
                NAVER_NEWS_API,
                headers=headers,
                params={"query": kw, "display": per_keyword, "sort": "date"},
                timeout=15,
            )
        except requests.RequestException as e:
            print(f"[collect] 네이버 검색 최종 실패 ({kw}): {e}", file=sys.stderr)
            continue

        for item in r.json().get("items", []):
            published = None
            pub = item.get("pubDate")
            if pub:
                try:
                    from email.utils import parsedate_to_datetime
                    published = parsedate_to_datetime(pub)
                except (TypeError, ValueError):
                    pass
            out.append(
                Article(
                    title=_strip_tags(item.get("title", "")),
                    # 네이버 링크보다 원문 링크를 우선한다 (originallink).
                    url=item.get("originallink") or item.get("link", ""),
                    source="뉴스",
                    kind="news",
                    published_at=published,
                    snippet=_strip_tags(item.get("description", ""))[:500],
                )
            )
    return [a for a in out if a.title and a.url]


def _within(article: Article, hours: int) -> bool:
    if article.published_at is None:
        return True  # 날짜를 못 읽은 건 살려두고 선별 단계에서 판단한다
    now = datetime.now(timezone.utc)
    at = article.published_at
    if at.tzinfo is None:
        at = at.replace(tzinfo=KST)
    return (now - at) <= timedelta(hours=hours)


def collect(config: dict) -> list[Article]:
    """설정에 따라 전체 소스를 수집하고 중복·제외어·기간 필터를 적용한다."""
    window = int(config.get("recency_hours", 48))
    excludes = [w for w in config.get("exclude_words", []) if w]

    articles: list[Article] = []
    if config.get("use_molit", True):
        articles += fetch_molit()
    articles += fetch_naver_news(config.get("keywords", []))

    seen: set[str] = set()
    result: list[Article] = []
    for a in articles:
        if a.key in seen:
            continue
        if any(w in a.title for w in excludes):
            continue
        if not _within(a, window):
            continue
        seen.add(a.key)
        result.append(a)

    result.sort(key=lambda x: (x.published_at is not None, x.published_at or datetime.min.replace(tzinfo=KST)), reverse=True)
    return result


def load_config(path: str = "config/sources.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


if __name__ == "__main__":
    cfg = load_config()
    items = collect(cfg)
    print(f"수집 {len(items)}건\n")
    for a in items[:30]:
        when = a.published_at.astimezone(KST).strftime("%m-%d %H:%M") if a.published_at else "  -  "
        print(f"[{a.source:6}] {when}  {a.title[:60]}")
