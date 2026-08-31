"""카드 이미지 렌더링. 스레드용 1080x1350 (4:5) PNG."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageDraw, ImageFont

from .models import Post

KST = timezone(timedelta(hours=9))

W, H = 1080, 1350
MARGIN = 90

BG = (16, 20, 28)
FG = (241, 244, 248)
ACCENT = (94, 176, 255)
MUTED = (138, 148, 163)

# 번들 폰트 → macOS → Linux(fonts-nanum) 순으로 찾는다.
# (경로, ttc 인덱스)
FONT_CANDIDATES = {
    "bold": [
        ("assets/fonts/Pretendard-Bold.ttf", 0),
        ("/System/Library/Fonts/AppleSDGothicNeo.ttc", 6),   # 6 = Bold
        ("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf", 0),
        ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf", 0),
    ],
    "regular": [
        ("assets/fonts/Pretendard-Regular.ttf", 0),
        ("/System/Library/Fonts/AppleSDGothicNeo.ttc", 0),   # 0 = Regular
        ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf", 0),
    ],
}


def _load(weight: str, size: int) -> ImageFont.FreeTypeFont:
    for path, index in FONT_CANDIDATES[weight]:
        if not os.path.exists(path):
            continue
        try:
            return ImageFont.truetype(path, size, index=index)
        except (OSError, ValueError):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    raise RuntimeError(
        "한글 폰트를 찾지 못했습니다. assets/fonts/ 에 Pretendard 를 넣거나 "
        "Linux 라면 'apt-get install fonts-nanum' 을 실행하세요."
    )


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    """한글은 공백이 적으므로 글자 단위로도 접는다."""
    lines: list[str] = []
    for para in text.split("\n"):
        line = ""
        for ch in para:
            trial = line + ch
            if draw.textlength(trial, font=font) <= max_width:
                line = trial
            else:
                # 공백이 있으면 마지막 공백에서 끊는 편이 자연스럽다
                if " " in line[-12:] and ch != " ":
                    cut = line.rfind(" ")
                    lines.append(line[:cut])
                    line = line[cut + 1:] + ch
                else:
                    lines.append(line)
                    line = ch
        lines.append(line)
    return [l for l in lines if l != ""] or [""]


def _fit(draw, text: str, weight: str, max_width: int, max_lines: int,
         start: int, minimum: int):
    """줄 수가 max_lines 안에 들어올 때까지 폰트를 줄인다."""
    size = start
    while size > minimum:
        font = _load(weight, size)
        lines = _wrap(draw, text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines
        size -= 4
    font = _load(weight, minimum)
    lines = _wrap(draw, text, font, max_width)
    return font, lines[:max_lines]


def render(post: Post, out_path: str, account: str = "") -> str:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    inner = W - MARGIN * 2

    # 상단 액센트 바
    draw.rectangle([MARGIN, 0, MARGIN + 96, 12], fill=ACCENT)

    base = H - MARGIN - 40
    rule_y = base - 46

    # 라벨은 위에 고정, 수치+헤드라인 블록은 남는 공간에 수직 중앙 정렬한다.
    # (그러지 않으면 콘텐츠가 위로 몰리고 아래 절반이 비어 보인다)
    y = 150
    if post.card_label:
        f_label = _load("bold", 34)
        draw.text((MARGIN, y), post.card_label, font=f_label, fill=ACCENT)
        y += 74

    block: list[tuple] = []   # (텍스트, 폰트, 줄높이, 색)
    if post.card_number:
        f, lines = _fit(draw, post.card_number, "bold", inner, 2, 150, 64)
        block += [(l, f, int(f.size * 1.18), FG) for l in lines]
        block.append(("", f, 40, FG))            # 수치와 헤드라인 사이 간격
    if post.card_headline:
        f, lines = _fit(draw, post.card_headline, "bold", inner, 5, 72, 40)
        block += [(l, f, int(f.size * 1.42), FG) for l in lines]

    block_h = sum(h for _, _, h, _ in block)
    top = y + max(0, ((rule_y - 60) - y - block_h) // 2)
    for text, font, line_h, color in block:
        if text:
            draw.text((MARGIN, top), text, font=font, fill=color)
        top += line_h

    # 하단: 구분선 + 날짜/출처/계정
    draw.line([MARGIN, rule_y, W - MARGIN, rule_y], fill=(48, 56, 68), width=2)

    f_small = _load("regular", 30)
    today = datetime.now(KST).strftime("%Y.%m.%d")
    draw.text((MARGIN, base), today, font=f_small, fill=MUTED)

    right = account or post.source_line
    if right:
        w = draw.textlength(right, font=f_small)
        draw.text((W - MARGIN - w, base), right, font=f_small, fill=MUTED)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    size_kb = os.path.getsize(out_path) / 1024
    print(f"[card] {out_path} ({W}x{H}, {size_kb:.0f}KB)")
    return out_path


if __name__ == "__main__":
    sample = Post(
        hook="", body="", takeaway="",
        card_label="오피스",
        card_number="2.4%",
        card_headline="서울 A급 오피스 공실률, 3분기 연속 하락",
        source_line="국토교통부",
    )
    render(sample, "out/sample-card.png", account="@commercial.re")
