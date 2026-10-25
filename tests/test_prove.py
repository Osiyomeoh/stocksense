import subprocess
import sys
import unittest

from app import config


class ProveTests(unittest.TestCase):
    def test_every_readme_claim_is_proven(self):
        p = subprocess.run([sys.executable, str(config.ROOT / "prove.py")], capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
