"""Apply infra/zetaris_usl.sql through the Zetaris REST API, one statement at a time.

Uses ZETARIS_REST_URL and ZETARIS_API_KEY from .env. Responses are not cached.

  python3 -I infra/apply_zetaris.py
"""
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.adapters import zetaris  # noqa: E402


def statements(text):
    body = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("--"))
    return [s.strip() for s in body.split(";\n") if s.strip().rstrip(";")]


def main():
    for sql in statements((ROOT / "infra" / "zetaris_usl.sql").read_text()):
        sql = sql.rstrip(";")
        print(f"> {' '.join(sql.split())[:90]}")
        out = zetaris._post("/sql-editor/sqls/run",
                            {"queryId": str(uuid.uuid4()), "sql": sql, "source": "SqlEditor", "limit": 10})
        print(f"  ok: {str(out)[:200]}")


if __name__ == "__main__":
    main()
