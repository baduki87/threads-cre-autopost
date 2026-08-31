"""파이프라인 전체가 주고받는 공통 데이터 구조."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any


def url_key(url: str) -> str:
    """추적 파라미터를 떼어낸 URL의 안정적인 해시. 중복 판정 키로 쓴다."""
    clean = re.sub(r"[?&](utm_[^&]*|fbclid|gclid)=[^&]*", "", url)
    clean = clean.rstrip("/?&")
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()[:16]


@dataclass
class Article:
    title: str
    url: str
    source: str          # "국토교통부" / "네이버뉴스" 등
    kind: str            # "policy" | "news"
    published_at: datetime | None = None
    snippet: str = ""

    @property
    def key(self) -> str:
        return url_key(self.url)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["published_at"] = self.published_at.isoformat() if self.published_at else None
        return d


@dataclass
class Pick:
    """선별 단계의 결과. article 이 None 이면 백업 콘텐츠로 전환한다."""
    article: Article | None
    score: int
    reason: str
    fallback_topic: str | None = None

    @property
    def is_fallback(self) -> bool:
        return self.article is None


@dataclass
class Post:
    """발행 직전의 완성된 콘텐츠."""
    hook: str
    body: str
    takeaway: str
    card_label: str
    card_number: str
    card_headline: str
    source_line: str
    tags: list[str] = field(default_factory=list)

    def render_text(self, limit: int = 500) -> str:
        """스레드 본문 조립. limit 자를 넘기지 않도록 뒤에서부터 줄인다."""
        tag_line = " ".join(f"#{t.lstrip('#')}" for t in self.tags)
        blocks = [self.hook, self.body, self.takeaway, self.source_line, tag_line]
        text = "\n\n".join(b.strip() for b in blocks if b and b.strip())
        if len(text) <= limit:
            return text
        # 태그 -> 출처 순으로 덜어내고, 그래도 넘치면 본문을 자른다.
        for drop in (4, 3):
            blocks[drop] = ""
            text = "\n\n".join(b.strip() for b in blocks if b and b.strip())
            if len(text) <= limit:
                return text
        return text[: limit - 1].rstrip() + "…"
