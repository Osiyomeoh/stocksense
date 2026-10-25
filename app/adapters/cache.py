"""The SAMPLE_MODE cache: every live Zetaris and Nightshift response is saved
under data/sample_cache/, keyed by a hash of the request, and replayed when
SAMPLE_MODE=true so the real logic runs with both services stopped.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app import config


class CacheMiss(RuntimeError):
    pass


def _path(kind: str, request: Any):
    key = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()[:16]
    return config.SAMPLE_DIR / kind / f"{key}.json"


def save(kind: str, request: Any, response: Any) -> None:
    path = _path(kind, request)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"request": request, "response": response}, indent=1, default=str), encoding="utf-8")


def load(kind: str, request: Any) -> Any:
    path = _path(kind, request)
    if not path.is_file():
        raise CacheMiss(f"SAMPLE_MODE: no cached {kind} response for this request; run once live to record it")
    return json.loads(path.read_text(encoding="utf-8"))["response"]
