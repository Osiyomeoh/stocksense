"""Zetaris over its direct REST API (POST /sql-editor/sqls/run).

Auth follows zetaris/getting-started scripts/zetaris_sql.py: a bearer API key
created in the Zetaris UI (Management -> API Tokens), the organisation ID and
a request ID. The key comes from ZETARIS_API_KEY and is never logged.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app import config
from app.adapters import cache


class ZetarisError(RuntimeError):
    pass


def _post(path: str, body: dict[str, Any]) -> Any:
    key = os.environ.get("ZETARIS_API_KEY")
    if not key:
        raise ZetarisError("ZETARIS_API_KEY is not set (create one in the Zetaris UI, Management -> API Tokens)")
    req = Request(
        config.ZETARIS_REST_URL + path,
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "X-Org-ID": config.ZETARIS_ORG_ID,
            "X-Request-ID": str(uuid.uuid4()),
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=300) as resp:
            return json.loads(resp.read().decode() or "null")
    except HTTPError as e:
        raise ZetarisError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}") from e
    except (URLError, OSError) as e:
        raise ZetarisError(f"Cannot reach Zetaris at {config.ZETARIS_REST_URL}: {getattr(e, 'reason', e)}") from e


def query(sql: str, limit: int = 1000) -> list[dict[str, Any]]:
    """Run one Lightning SQL statement and return its rows as dicts.

    Zetaris returns every value as a string (or null); callers cast. In
    SAMPLE_MODE the recorded response for the same SQL is replayed.
    """
    request = {"sql": sql, "limit": limit}
    if config.SAMPLE_MODE:
        out = cache.load("zetaris", request)
    else:
        out = _post("/sql-editor/sqls/run", {"queryId": str(uuid.uuid4()), "source": "SqlEditor", **request})
        cache.save("zetaris", request, out)
    if not isinstance(out, dict) or "headers" not in out:
        raise ZetarisError("Unexpected response shape from Zetaris (no headers)")
    return [dict(zip(out["headers"], row)) for row in out.get("data") or []]
