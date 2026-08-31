"""Claude API 호출 공통 래퍼.

응답은 프롬프트로 JSON 을 지시하고 직접 파싱한다. SDK 버전이 올라가도
깨지지 않고, 실패했을 때 원문을 그대로 로그로 볼 수 있어 디버깅이 쉽다.
"""
from __future__ import annotations

import json
import re
import sys

import anthropic

MODEL = "claude-opus-5"


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def _extract_json(text: str) -> dict:
    """모델이 코드펜스나 설명을 덧붙여도 JSON 객체를 건져낸다."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError(f"JSON 을 찾지 못했습니다:\n{text[:500]}")
        candidate = text[start : end + 1]
    return json.loads(candidate)


def ask_json(system: str, prompt: str, *, effort: str = "high", max_tokens: int = 8000) -> dict:
    """JSON 객체 하나를 돌려받는다. 파싱 실패 시 한 번만 재시도한다."""
    client = _client()
    messages = [{"role": "user", "content": prompt}]

    for attempt in (1, 2):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            messages=messages,
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        try:
            return _extract_json(text)
        except (ValueError, json.JSONDecodeError) as e:
            if attempt == 2:
                raise
            print(f"[llm] JSON 파싱 실패, 재시도합니다: {e}", file=sys.stderr)
            messages = [
                {"role": "user", "content": prompt},
                {"role": "user", "content": "직전 응답을 JSON 객체 하나만으로 다시 출력하세요. 다른 텍스트는 붙이지 마세요."},
            ]
    raise RuntimeError("unreachable")
