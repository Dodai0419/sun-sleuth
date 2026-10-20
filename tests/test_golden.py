"""Golden tests: every case's stdout must match upstream geo-sleuth sun.py byte for byte."""
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = Path(__file__).resolve().parent / "golden"
TOOL = ROOT / "sun_sleuth.py"

try:
    from zoneinfo import ZoneInfo
    ZoneInfo("Asia/Shanghai")
    HAVE_TZDATA = True
except Exception:  # Windows without the tzdata package
    HAVE_TZDATA = False


def run(args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, env=env)


class Golden(unittest.TestCase):
    def test_cases(self):
        cases = sorted(GOLDEN.glob("case*.args"), key=lambda p: int(p.stem[4:]))
        self.assertGreaterEqual(len(cases), 15)
        for case in cases:
            args = shlex.split(case.read_text(encoding="utf-8"))
            with self.subTest(case=case.stem, args=" ".join(args)):
                if "--tz" in args and not HAVE_TZDATA:
                    self.skipTest("tzdata not installed")
                r = run(args)
                self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
                want = case.with_suffix(".out").read_bytes()
                self.assertEqual(r.stdout.replace(b"\r\n", b"\n"), want.replace(b"\r\n", b"\n"))

    def test_points_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "pts.json"
            r = run(["locate", "--time", "2024-03-20T12:00", "--sun-azimuth", "180", "--az-tol", "5",
                     "--bbox", "-10,-20,10,20", "--step", "0.5", "--points", str(out)])
            self.assertEqual(r.returncode, 0)
            pts = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(len(pts), 35)
            self.assertEqual(pts, json.loads((GOLDEN / "points8.json").read_text(encoding="utf-8")))

    def test_refraction_bound_used_by_prefilter(self):
        sys.path.insert(0, str(ROOT))
        import sun_sleuth
        for i in range(-90000, 90001):
            r = sun_sleuth._refraction(i / 1000)
            self.assertTrue(0 <= r <= 0.6, (i, r))

    def test_needs_a_target(self):
        r = run(["locate", "--time", "2024-03-20T12:00", "--bbox", "0,0,1,1"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(b"Need at least one of", r.stderr)


if __name__ == "__main__":
    unittest.main()
