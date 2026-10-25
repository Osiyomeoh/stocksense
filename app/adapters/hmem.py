"""H-MEM, Meterless's memory engine, through a small Node sidecar
(memory/hmem_cli.ts over the vendored reference in vendor/hmem).

Each call runs one operation; state persists in config.HMEM_DIR.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any

from app import config

CLI = config.ROOT / "memory" / "hmem_cli.ts"


class HMemError(RuntimeError):
    pass


def call(op: str, **args: Any) -> Any:
    env = {**os.environ, "HMEM_DIR": str(config.HMEM_DIR)}
    try:
        p = subprocess.run(["node", "--experimental-transform-types", "--no-warnings", str(CLI)],
                           input=json.dumps({"op": op, **args}), capture_output=True, text=True,
                           env=env, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise HMemError(f"cannot run the H-MEM sidecar (is Node >= 23.6 installed?): {e}") from e
    if p.returncode:
        raise HMemError(p.stderr.strip().splitlines()[-1] if p.stderr.strip() else f"exit {p.returncode}")
    return json.loads(p.stdout)


def add(content: str, tags: list[str], confidence: float, source: str, label: str) -> dict:
    return call("add", memory={"content": content, "type": "factual", "layer": "long_term", "tags": tags,
                               "confidence": confidence, "source": source,
                               "provenance": {"origin": "user_correction", "label": label}})


def find(*tags: str) -> list[dict]:
    return call("list", tags=list(tags))


def feedback(memory_id: str, kind: str) -> dict:
    return call("feedback", id=memory_id, kind=kind)
