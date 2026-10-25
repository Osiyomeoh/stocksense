"""Nightshift, the primary AI provider: an OpenAI-compatible endpoint
(default http://127.0.0.1:8088/v1, model meterless/auto).

Every call returns the model that answered, so the trace can name it.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app import config
from app.adapters import cache


class NightshiftError(RuntimeError):
    pass


def _token() -> str:
    try:
        return config.NIGHTSHIFT_TOKEN_FILE.read_text().strip()
    except OSError as e:
        raise NightshiftError(f"No Nightshift runtime token at {config.NIGHTSHIFT_TOKEN_FILE}; is Nightshift installed and started?") from e


def chat(messages: list[dict[str, str]], model: str | None = None, temperature: float = 0) -> dict[str, Any]:
    """Return {"text", "model", "raw"}. `model` is the one the response names."""
    request = {"model": model or config.NIGHTSHIFT_MODEL, "messages": messages, "temperature": temperature}
    if config.SAMPLE_MODE:
        raw = cache.load("nightshift", request)
    else:
        req = Request(
            config.NIGHTSHIFT_URL + "/chat/completions",
            data=json.dumps(request).encode(),
            method="POST",
            headers={"Content-Type": "application/json", "meterless-app": config.NIGHTSHIFT_APP,
                     "Authorization": f"Bearer {_token()}"},
        )
        try:
            with urlopen(req, timeout=180) as resp:
                raw = json.loads(resp.read().decode())
        except HTTPError as e:
            raise NightshiftError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}") from e
        except (URLError, OSError) as e:
            raise NightshiftError(f"Cannot reach Nightshift at {config.NIGHTSHIFT_URL}: {getattr(e, 'reason', e)}") from e
        cache.save("nightshift", request, raw)
    try:
        text = raw["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise NightshiftError("Unexpected response shape from Nightshift") from e
    return {"text": text, "model": raw.get("model") or request["model"], "raw": raw}
