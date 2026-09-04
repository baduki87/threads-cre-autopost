"""LLM 호출 공통 래퍼. 무료(Gemini)와 유료(Claude)를 바꿔 쓸 수 있다.

LLM_PROVIDER 환경변수로 고른다:
  auto    (기본) 있는 키를 보고 알아서 고른다. Claude 키가 있으면 Claude 우선
  gemini  Google Gemini 무료 등급 (신용카드 불필요)
  claude  Anthropic Claude (유료)

응답은 프롬프트로 JSON 을 지시하고 직접 파싱한다. 어느 제공자를 쓰든
같은 방식이라 갈아탈 때 select.py / compose.py 는 손댈 필요가 없다.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

import requests

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5")
GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"

_gemini_model_cache: str | None = None


# ---------------------------------------------------------------- 공통

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


def provider() -> str:
    choice = os.environ.get("LLM_PROVIDER", "auto").strip().lower()
    if choice in {"claude", "gemini"}:
        return choice
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude"
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    raise RuntimeError(
        "LLM 키가 없습니다. 무료로 쓰려면 GEMINI_API_KEY 를, "
        "Claude 를 쓰려면 ANTHROPIC_API_KEY 를 설정하세요."
    )


# ---------------------------------------------------------------- Gemini

def list_gemini_models() -> list[str]:
    """이 키로 쓸 수 있는 모델 목록. 모델명이 자주 바뀌어 하드코딩하지 않는다."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY 가 설정되지 않았습니다.")
    r = requests.get(f"{GEMINI_API}/models", params={"key": key}, timeout=20)
    r.raise_for_status()
    out = []
    for m in r.json().get("models", []):
        if "generateContent" in (m.get("supportedGenerationMethods") or []):
            out.append(m["name"].removeprefix("models/"))
    return out


def _version_score(name: str) -> float:
    """이름에서 버전 숫자를 뽑아 최신을 고른다. gemini-3.6-flash -> 3.6"""
    m = re.search(r"(\d+(?:\.\d+)?)", name)
    return float(m.group(1)) if m else 0.0


def resolve_gemini_model() -> str:
    """무료 등급에서 쓸 수 있는 flash 계열 중 가장 최신을 고른다."""
    global _gemini_model_cache
    if _gemini_model_cache:
        return _gemini_model_cache

    forced = os.environ.get("GEMINI_MODEL")
    if forced:
        _gemini_model_cache = forced
        return forced

    models = list_gemini_models()
    # 무료 등급은 flash 계열만 열려 있다. 미리보기/실험판은 뒤로 미룬다.
    flash = [m for m in models if "flash" in m and "lite" not in m]
    stable = [m for m in flash if not re.search(r"preview|exp|latest", m)]
    pool = stable or flash or models
    if not pool:
        raise RuntimeError(f"쓸 수 있는 모델이 없습니다. 조회 결과: {models[:10]}")

    chosen = sorted(pool, key=_version_score, reverse=True)[0]
    _gemini_model_cache = chosen
    print(f"[llm] Gemini 모델 자동 선택: {chosen}", file=sys.stderr)
    return chosen


# 일시적인 장애들. 503(과부하)은 무료 등급에서 실제로 자주 난다.
_RETRYABLE = {429, 500, 502, 503, 504}


def _alternate_models(tried: set[str], limit: int = 2) -> list[str]:
    """과부하일 때 대신 쓸 flash 계열.

    이미 시도한 모델은 제외한다. 안 그러면 같은 모델을 다시 집어와
    무한히 도는 사고가 난다.
    """
    try:
        models = list_gemini_models()
    except Exception:
        return []
    flash = [m for m in models
             if "flash" in m and m not in tried and not re.search(r"preview|exp", m)]
    return sorted(flash, key=_version_score, reverse=True)[:limit]


def _gemini_once(model: str, key: str, body: dict) -> requests.Response:
    return requests.post(
        f"{GEMINI_API}/models/{model}:generateContent",
        params={"key": key},
        json=body,
        timeout=120,
    )


def _ask_gemini(system: str, prompt: str, max_tokens: int, tries: int = 3) -> str:
    """과부하·한도 초과는 재시도하고, 그래도 안 되면 다른 flash 모델로 넘어간다.

    하루 한 번 도는 자동화라 한 번의 일시적 실패로 그날을 통째로 잃으면 안 된다.
    """
    key = os.environ["GEMINI_API_KEY"]
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            # JSON 만 내놓도록 강제한다. 파싱 실패가 크게 줄어든다.
            "responseMimeType": "application/json",
            "maxOutputTokens": max_tokens,
        },
    }

    primary = resolve_gemini_model()
    candidates_models = [primary]
    tried: set[str] = set()
    fetched_alternates = False
    last_err = ""

    while candidates_models:
        model = candidates_models.pop(0)
        tried.add(model)
        for attempt in range(1, tries + 1):
            try:
                r = _gemini_once(model, key, body)
            except requests.RequestException as e:
                last_err = f"연결 실패: {e}"
                if attempt < tries:
                    time.sleep(2 ** attempt)
                    continue
                break

            if r.ok:
                data = r.json()
                cands = data.get("candidates") or []
                if not cands:
                    raise RuntimeError(f"Gemini 응답이 비어 있습니다: {json.dumps(data)[:400]}")
                parts = cands[0].get("content", {}).get("parts") or []
                return "".join(p.get("text", "") for p in parts)

            last_err = f"HTTP {r.status_code}: {r.text[:250]}"
            if r.status_code not in _RETRYABLE:
                raise RuntimeError(f"Gemini 호출 실패 ({model}) — {last_err}")

            if attempt < tries:
                wait = 2 ** attempt
                print(f"[llm] {model} 일시 장애({r.status_code}) — {wait}초 후 재시도 "
                      f"({attempt}/{tries})", file=sys.stderr)
                time.sleep(wait)

        # 이 모델은 계속 실패했다. 대체 모델을 딱 한 번만 가져와 갈아탄다.
        if not candidates_models and not fetched_alternates:
            fetched_alternates = True
            alts = _alternate_models(tried)
            if alts:
                print(f"[llm] {model} 이 계속 실패해 {alts[0]} 로 전환합니다.", file=sys.stderr)
                candidates_models = alts

    raise RuntimeError(
        "Gemini 호출이 재시도와 모델 전환에도 실패했습니다.\n"
        f"마지막 오류 — {last_err}"
    )


# ---------------------------------------------------------------- Claude

def _ask_claude(system: str, prompt: str, effort: str, max_tokens: int) -> str:
    import anthropic

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=max_tokens,
        system=system,
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


# ---------------------------------------------------------------- 진입점

def ask_json(system: str, prompt: str, *, effort: str = "high",
             max_tokens: int = 8000) -> dict:
    """JSON 객체 하나를 돌려받는다. 파싱 실패 시 한 번만 재시도한다."""
    which = provider()
    retry_note = "\n\n반드시 JSON 객체 하나만 출력하세요. 다른 텍스트는 붙이지 마세요."

    for attempt in (1, 2):
        body = prompt if attempt == 1 else prompt + retry_note
        if which == "gemini":
            text = _ask_gemini(system, body, max_tokens)
        else:
            text = _ask_claude(system, body, effort, max_tokens)
        try:
            return _extract_json(text)
        except (ValueError, json.JSONDecodeError) as e:
            if attempt == 2:
                raise
            print(f"[llm] JSON 파싱 실패, 재시도합니다: {e}", file=sys.stderr)
    raise RuntimeError("unreachable")


if __name__ == "__main__":
    print(f"제공자: {provider()}")
    if provider() == "gemini":
        print("사용 가능한 모델:")
        for m in list_gemini_models():
            print(f"  - {m}")
        print(f"\n자동 선택: {resolve_gemini_model()}")
