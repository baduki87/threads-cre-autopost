"""프로젝트 공통 초기화.

.env 파일이 있으면 읽어서 환경변수로 올린다.
터미널을 새로 열 때마다 export 를 다시 치지 않아도 되게 하려는 것.
이미 설정된 환경변수는 덮어쓰지 않는다 (GitHub Actions 의 시크릿이 우선).
"""
from __future__ import annotations

import os
from pathlib import Path

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _load_dotenv() -> None:
    if not _ENV_PATH.exists():
        return
    for raw in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()
