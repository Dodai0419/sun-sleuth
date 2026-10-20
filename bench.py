"""Time sun_sleuth.py (and optionally upstream geo-sleuth sun.py) on the README benchmark inputs.

  python bench.py                         # this repo only
  python bench.py --upstream path/to/sun.py   # also time upstream and byte-compare stdout
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

CASES = {
    "locate 0.1deg, 1 time": "locate --time 2023-08-15T16:20+08:00 --ratio 1.2 --tol 1.5 --bbox 34,110,42,122",
    "locate 0.05deg, +/-30 min": "locate --time 2023-08-15T16:20+08:00 --elev 40 --shadow-bearing 60 --az-tol 10 "
                                 "--time-tol 30 --bbox 20,100,45,130 --step 0.05",
    "when, 366 days": "when --at 30.25,120.16 --dates 2024-01-01:2024-12-31 --elev 40 --shadow-bearing 330",
}


def timed(script, args):
    t = time.perf_counter()
    out = subprocess.run([sys.executable, str(script), *args.split()], capture_output=True, check=True).stdout
    return time.perf_counter() - t, out


ap = argparse.ArgumentParser()
ap.add_argument("--upstream", type=Path)
ns = ap.parse_args()
mine = Path(__file__).with_name("sun_sleuth.py")
for name, args in CASES.items():
    t1, o1 = timed(mine, args)
    line = f"{name:28s} this repo {t1:6.2f}s"
    if ns.upstream:
        t0, o0 = timed(ns.upstream, args)
        line += f"   upstream {t0:6.2f}s   same output: {o0 == o1}"
    print(line)
