"""Regenerate output_examples/ from input_examples/ by running each one in SAMPLE_MODE.

  python3 examples/make_outputs.py
"""

import json
import os
import sys
from pathlib import Path

os.environ["SAMPLE_MODE"] = "true"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import run  # noqa: E402

for src in sorted((HERE / "input_examples").glob("*.json")):
    status, body = run.handle(src.read_text())
    out = HERE / "output_examples" / src.name
    out.write_text(json.dumps({"http_status": status, "body": body}, indent=1, ensure_ascii=False, default=str) + "\n")
    print(f"{src.name}: {status}")
