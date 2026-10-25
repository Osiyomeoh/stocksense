"""logs/trace-<run_id>.jsonl, one JSON object per agent action.

Fields are the ones the hackathon guide requires, in its order.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app import config

FIELDS = (
    "timestamp", "run_id", "agent_name", "action", "input_summary", "output_summary",
    "target_agent", "model", "confidence", "retry_count", "status",
)


class Trace:
    def __init__(self, run_id: str, log_dir: Path = config.LOG_DIR):
        self.run_id = run_id
        log_dir.mkdir(parents=True, exist_ok=True)
        self.path = log_dir / f"trace-{run_id}.jsonl"

    def log(
        self,
        agent_name: str,
        action: str,
        input_summary: str = "",
        output_summary: str = "",
        *,
        target_agent: str | None = None,
        model: str | None = None,
        confidence: float | None = None,
        retry_count: int = 0,
        status: str = "ok",
        **extra: Any,
    ) -> dict[str, Any]:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "run_id": self.run_id,
            "agent_name": agent_name,
            "action": action,
            "input_summary": input_summary,
            "output_summary": output_summary,
            "target_agent": target_agent,
            "model": model,
            "confidence": confidence,
            "retry_count": retry_count,
            "status": status,
            **extra,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")
        return event
