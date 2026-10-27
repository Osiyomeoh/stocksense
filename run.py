"""StockSense "Before the Rain": one run, from the CLI or over HTTP.

  python3 run.py '{"as_of": "2022-07-04"}'     # one run, JSON to stdout
  python3 run.py --serve                        # POST /run on 0.0.0.0:8080
  python3 run.py --feedback "S2 was late again"  # teach the Memory Keeper (also POST /feedback)

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
from app.adapters import cache, hmem, nightshift, zetaris
from app.agents import memory_keeper
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
    hmem.HMemError: (502, "hmem_unavailable"),
}


MAX_NOTE = 500  # each clause is one H-MEM call; a pharmacist's edit is a sentence or two


def feedback(payload: Any) -> dict[str, Any]:
    note = payload.get("note") if isinstance(payload, dict) else None
    if not isinstance(note, str) or not note.strip():
        raise InputError('feedback must be {"note": "<the pharmacist\'s edit>"}')
    if len(note) > MAX_NOTE:
        raise InputError(f"a note is at most {MAX_NOTE} characters")
    return {"note": note, "changes": memory_keeper.learn(note)}


def handle(raw: str, fn=run) -> tuple[int, dict[str, Any]]:
    try:
        return 200, fn(json.loads(raw or "{}"))
    except tuple(ERRORS) as e:
        status, kind = next(v for t, v in ERRORS.items() if isinstance(e, t))
        return status, {"error": {"type": kind, "message": str(e)}}


MAX_BODY = 4096
UI = config.ROOT / "app" / "ui" / "index.html"
IMG = UI.parent / "img"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/":
            return self._raw(UI.read_bytes(), "text/html; charset=utf-8")
        name = self.path.removeprefix("/img/")
        if self.path.startswith("/img/") and name in {p.name for p in IMG.glob("*.jpg")}:
            return self._raw((IMG / name).read_bytes(), "image/jpeg")
        run_id = self.path.removeprefix("/trace/")
        path = config.LOG_DIR / f"trace-{run_id}.jsonl"
        if self.path.startswith("/trace/") and run_id.isalnum() and path.is_file():
            return self._send(200, [json.loads(l) for l in path.read_text().splitlines() if l])
        self._send(404, {"error": {"type": "not_found", "message": "GET /, /img/<name> or /trace/<run_id>; POST /run"}})

    def do_POST(self) -> None:
        fn = {"/run": run, "/feedback": feedback}.get(self.path)
        if fn is None:
            return self._send(404, {"error": {"type": "not_found", "message": "POST /run or /feedback"}})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 <= length <= MAX_BODY:
                raise ValueError
        except ValueError:
            return self._send(400, {"error": {"type": "bad_input", "message": f"Content-Length must be 0..{MAX_BODY}"}})
        self._send(*handle(self.rfile.read(length).decode(errors="replace"), fn))

    def _raw(self, data: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

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
    if argv[:1] == ["--feedback"]:
        status, body = handle(json.dumps({"note": " ".join(argv[1:])}), feedback)
    else:
        status, body = handle(argv[0] if argv else sys.stdin.read())
    print(json.dumps(body, indent=1, default=str))
    return 0 if status == 200 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
