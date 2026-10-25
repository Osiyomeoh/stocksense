"""StockSense "Before the Rain": one run, from the CLI or over HTTP.

  python3 run.py '{"as_of": "2022-07-04"}'     # one run, JSON to stdout
  python3 run.py --serve                        # POST /run on 0.0.0.0:8080

Errors come back as {"error": {"type", "message"}} with a non-zero exit code
(CLI) or a 4xx/5xx status (HTTP).
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from app import config, pipeline
from app.adapters import cache, nightshift, zetaris
from app.data import NoSnapshot
from app.trace import Trace


class InputError(ValueError):
    pass


def parse_input(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise InputError("input must be a JSON object")
    try:
        as_of = date.fromisoformat(str(payload.get("as_of", "")))
    except ValueError as e:
        raise InputError("as_of must be an ISO date, e.g. 2022-07-04") from e
    return {"as_of": as_of.isoformat(), "session": payload.get("session")}


def run(payload: Any) -> dict[str, Any]:
    args = parse_input(payload)
    run_id = uuid.uuid4().hex[:12]
    trace = Trace(run_id)
    result = pipeline.run(args["as_of"], trace)
    return {"run_id": run_id, "as_of": args["as_of"], "sample_mode": config.SAMPLE_MODE,
            **result, "trace": str(trace.path.relative_to(config.ROOT))}


ERRORS: dict[type, tuple[int, str]] = {
    InputError: (400, "bad_input"),
    NoSnapshot: (404, "no_snapshot"),
    json.JSONDecodeError: (400, "bad_json"),
    cache.CacheMiss: (503, "sample_cache_miss"),
    zetaris.ZetarisError: (502, "zetaris_unavailable"),
    nightshift.NightshiftError: (502, "nightshift_unavailable"),
}


def handle(raw: str) -> tuple[int, dict[str, Any]]:
    try:
        return 200, run(json.loads(raw or "{}"))
    except tuple(ERRORS) as e:
        status, kind = next(v for t, v in ERRORS.items() if isinstance(e, t))
        return status, {"error": {"type": kind, "message": str(e)}}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path != "/run":
            return self._send(404, {"error": {"type": "not_found", "message": "POST /run"}})
        length = int(self.headers.get("Content-Length") or 0)
        self._send(*handle(self.rfile.read(length).decode()))

    def _send(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main(argv: list[str]) -> int:
    if argv[:1] == ["--serve"]:
        port = int(os.environ.get("PORT", "8080"))
        print(f"POST /run on 0.0.0.0:{port} (SAMPLE_MODE={config.SAMPLE_MODE})", file=sys.stderr)
        ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
    status, body = handle(argv[0] if argv else sys.stdin.read())
    print(json.dumps(body, indent=1, default=str))
    return 0 if status == 200 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
