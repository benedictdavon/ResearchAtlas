"""Smoke test: the end-to-end demo in examples/demo runs and shows what it promises."""

import subprocess
import sys
import unittest
from pathlib import Path

DEMO = Path(__file__).resolve().parent.parent / "examples/demo/run_demo.py"


class DemoTests(unittest.TestCase):
    def test_demo_runs_end_to_end(self):
        proc = subprocess.run([sys.executable, str(DEMO)], capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout
        self.assertIn("scanned 3 sessions (1 codex, 1 claude, 1 copilot)", out)
        self.assertIn("marked 3 session(s) reviewed", out)
        self.assertIn("New sessions (not reviewed): 1", out)
        self.assertRegex(out, r"missing\s+\S+/research/birdsong/data/raw/2026-03-field\s+<- INDEX\.md:\d+")
        self.assertRegex(out, r"\S+/archive/birdsong/2026-03-field")


if __name__ == "__main__":
    unittest.main()
