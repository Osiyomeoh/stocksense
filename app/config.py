"""Settings from the environment, with .env at the repo root as a fallback.

Secrets are read here and never printed or logged.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path = ROOT / ".env") -> None:
    """Load KEY=VALUE lines without overriding variables already set."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in ("1", "true", "yes")


load_env()

SAMPLE_MODE = flag("SAMPLE_MODE")
SAMPLE_DIR = ROOT / "data" / "sample_cache"
LOG_DIR = ROOT / "logs"

ZETARIS_REST_URL = os.environ.get("ZETARIS_REST_URL", "http://localhost:8888/api/v1.0").rstrip("/")
ZETARIS_ORG_ID = os.environ.get("ZETARIS_ORG_ID") or "1"  # an empty .env line means the default
CLINIC_RISK_TABLE = os.environ.get("CLINIC_RISK_TABLE", "lightning.metastore.stocksense.k2_usl.clinic_risk")

NIGHTSHIFT_URL = os.environ.get("NIGHTSHIFT_URL", "http://127.0.0.1:8088/v1").rstrip("/")
NIGHTSHIFT_MODEL = os.environ.get("NIGHTSHIFT_MODEL", "meterless/auto")
# Nightshift mints a local runtime token on first start; the app reads it from there.
NIGHTSHIFT_TOKEN_FILE = Path(os.environ.get(
    "NIGHTSHIFT_TOKEN_FILE",
    Path.home() / "Library" / "Application Support" / "ai.meterless.nightshift.m1m4" / "runtime-token"))
NIGHTSHIFT_APP = "stocksense"  # the meterless-app header Nightshift requires
