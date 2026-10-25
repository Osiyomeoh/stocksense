import os
import tempfile

# Keep H-MEM state out of data/memory while tests run.
os.environ.setdefault("HMEM_DIR", tempfile.mkdtemp(prefix="hmem-test-"))
