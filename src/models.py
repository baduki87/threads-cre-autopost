"""파이프라인 전체가 주고받는 공통 데이터 구조."""
from __future__ import annotations

import hashlib
import re
import sys
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
class Memo:
    """노션에 직접 넣은 현장 메모.

    이 시스템에서 '의견'의 유일한 출처다. 메모가 없으면 판단을 쓰지 않는다.
    """
    page_id: str
    title: str
    text: str


@dataclass
class Pick:
    """선별 단계의 결과.

    memo 가 있으면 최우선. 없고 article 도 None 이면 백업 콘텐츠로 전환한다.
    """
    article: Article | None
    score: int
    reason: str
    fallback_topic: str | None = None
    memo: Memo | None = None

    @property
    def is_memo(self) -> bool:
        return self.memo is not None

    @property
    def is_fallback(self) -> bool:
        return self.article is None and self.memo is None


BODY_LINES = 3      # 본문 줄 수. 짧을수록 반응이 좋았다 (docs/account-analysis.md)


@dataclass
class Post:
    """발행 직전의 완성된 콘텐츠.

    opinion 과 question 이 반응을 가른다 (docs/account-analysis.md 참고).
    opinion 은 메모가 있을 때만 채운다 — 없는 날 지어내면 안 된다.
    detail 은 본문에 안 들어간 현장 정보로, 발행 직후 첫 댓글로 붙는다.
    """
    hook: str
    body: str
    card_label: str
    card_number: str
    card_headline: str
    source_line: str
    opinion: str = ""      # 본인 판단 한 줄. 메모에서만 나온다
    question: str = ""     # 답하기 쉬운 질문 한 줄
    detail: str = ""       # 첫 댓글에 붙는 상세. 본문과 중복되지 않는다
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # 프롬프트로 "3줄"을 지시해도 모델이 더 뱉는 경우가 있다.
        # 본문 길이는 이 계정 성과와 직결되므로 코드에서 강제한다.
        lines = [ln.strip() for ln in self.body.splitlines() if ln.strip()]
        if len(lines) > BODY_LINES:
            print(f"[post] 본문이 {len(lines)}줄이라 앞 {BODY_LINES}줄만 씁니다.",
                  file=sys.stderr)
            lines = lines[:BODY_LINES]
        self.body = "\n".join(lines)

    def render_text(self, limit: int = 500) -> str:
        """스레드 본문 조립. limit 자를 넘기지 않도록 덜 중요한 것부터 덜어낸다.

        질문은 댓글을 만드는 장치라 마지막까지 지킨다.
        태그는 실제 계정이 쓰지 않으므로 보통 비어 있다.
        """
        tag_line = " ".join(f"#{t.lstrip('#')}" for t in self.tags)
        blocks = [self.hook, self.body, self.opinion, self.question,
                  self.source_line, tag_line]

        def assemble(bs: list[str]) -> str:
            return "\n\n".join(b.strip() for b in bs if b and b.strip())

        text = assemble(blocks)
        if len(text) <= limit:
            return text

        # 태그 → 출처 순으로 덜어낸다. 의견과 질문은 남긴다.
        for drop in (5, 4):
            blocks[drop] = ""
            text = assemble(blocks)
            if len(text) <= limit:
                return text

        # 그래도 넘치면 본문만 줄인다. 의견·질문은 끝까지 지킨다.
        # 남는 자리 = 제한 - (지킬 블록들 + 그 사이 구분자 "\n\n")
        keep = [b.strip() for b in (self.hook, self.opinion, self.question) if b and b.strip()]
        room = limit - sum(len(b) for b in keep) - 2 * len(keep)
        if room > 40:
            blocks[1] = self.body[: room - 1].rstrip() + "…"
            text = assemble(blocks)
            if len(text) <= limit:
                return text

        return assemble(blocks)[: limit - 1].rstrip() + "…"

    def render_detail(self, limit: int = 500) -> str:
        """첫 댓글 본문. 비어 있으면 빈 문자열 — 그러면 댓글을 달지 않는다."""
        text = (self.detail or "").strip()
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "…"
