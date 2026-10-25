import os
import tempfile

# Keep H-MEM state out of data/memory while tests run.
os.environ.setdefault("HMEM_DIR", tempfile.mkdtemp(prefix="hmem-test-"))


def fresh_memory(test):
    """Give one test its own empty H-MEM directory."""
    from pathlib import Path
    from unittest import mock

    from app import config
    p = mock.patch.object(config, "HMEM_DIR", Path(tempfile.mkdtemp(prefix="hmem-")))
    p.start()
    test.addCleanup(p.stop)
