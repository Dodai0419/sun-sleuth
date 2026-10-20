<div align="center">

# sun-sleuth

**Find where and when a photo was taken from its shadows. One stdlib file, same answers as geo-sleuth.**

A lean, faster port of the sun-geometry tool inside [geo-sleuth](https://github.com/Oldcircle/geo-sleuth) (3k+ stars), the agent skill that geolocates photos. Works with **Claude Code** and **Codex**.

![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg) ![Status: prototype](https://img.shields.io/badge/status-prototype-orange.svg)

</div>

## Quick start
```bash
git clone https://github.com/Dodai0419/sun-sleuth && cd sun-sleuth
python sun_sleuth.py locate --time 2023-08-15T16:20+08:00 --elev 40 --shadow-bearing 60 --az-tol 10 --time-tol 30 --bbox 34,110,42,122
```
```
{
 "utc": "2023-08-15T08:20+00:00",
 "target_elev": 40.0,
 "target_sun_azimuth": 240.0,
 "matched_points": 55,
 ...
```

```bash
python sun_sleuth.py pos --at 39.9042,116.4074 --time 2023-08-15T16:20+08:00
python sun_sleuth.py when --at 30.25,120.16 --dates 2024-01-01:2024-03-31 --elev 40 --shadow-bearing 330
python sun_sleuth.py ratio --shadow 1.2
python sun_sleuth.py dish --lat 31.2 --sat 92.2 --azimuth 215
```

## The problem
- A fine `locate` scan (0.05° grid, ±30 min capture-time window) takes geo-sleuth's `sun.py` about 100 s, because it recomputes the same time-only solar terms for every grid cell.
- `sun.py` lives inside a large skill. If you only need the sun geometry, you still pull in the whole repo, and Pillow for the map overlay.
- On Windows without `tzdata`, `--tz Asia/Shanghai` crashes with a traceback.

## The solution
| Idea | Fixes |
|------|-------|
| **Hoist time-only work** (solar declination, equation of time, hour angle per longitude) out of the grid loop | Same floating-point operations, done once per time or longitude instead of once per cell |
| **Exact pre-filter on cos(zenith)** (refraction is always 0 to 0.6°, so a cell more than 1° outside the band cannot match) | Skips `acos`/`tan` for most cells and all night-time steps. Every surviving cell still gets upstream's exact test |
| **One stdlib file**, golden-tested against upstream output byte for byte | No Pillow. A clear error instead of a traceback when `tzdata` is missing; an offset like `+08:00` in `--time` needs no tzdata at all |

Subcommands kept: `pos`, `ratio`, `locate`, `when`, `dish`. Dropped: `street`, `facing`, `compass` and the `--mosaic` map overlay (use upstream for those).

## Use with Claude Code
```bash
/plugin marketplace add Dodai0419/sun-sleuth
/plugin install sun-sleuth@sun-sleuth
```

## Use with Codex (ChatGPT)
```bash
git clone https://github.com/Dodai0419/sun-sleuth && cp -r sun-sleuth/skills/* ~/.codex/skills/
```
Or copy `AGENTS.md` into your project root.

## Benchmarks
`python bench.py --upstream path/to/geo-sleuth/skills/geo-sleuth/scripts/sun.py` runs each command once with both tools, times the whole process, and byte-compares stdout.

| | geo-sleuth `sun.py` | sun-sleuth |
|-|-|-|
| `locate`, 0.1° grid over 8°×12°, 1 time | 0.61–1.87 s | 0.27–1.04 s |
| `locate`, 0.05° grid over 25°×30°, ±30 min (13 times) | 98.8–143.2 s | 5.3–12.9 s |
| `when`, 366 days at 2-min steps | 6.6–12.0 s | 3.9–7.5 s |
| same stdout | — | yes, all three |
| lines of code | 589 (8 subcommands) | 368 (5 subcommands) |
| runtime dependencies | Pillow (for `--mosaic`) | none |

Windows 11, Python 3.11.1. Ranges cover 2–3 runs of `bench.py` (the slowest run was taken while the machine was busy; each row's two columns ran back to back, so the ratio holds per run), and Python start-up alone is about 0.3–0.7 s. Correctness: `tests/` holds 15 golden outputs recorded from upstream `sun.py` (pos, ratio, locate, when, dish, including negative coordinates and DST zones), plus a `--points` file check. The three time-zone cases are skipped when `tzdata` is not installed.

## Inspired by
- [Oldcircle/geo-sleuth](https://github.com/Oldcircle/geo-sleuth): the original `sun.py` (MIT). The NOAA/Meeus formulas and the output formats come from it unchanged.

## Roadmap
- [ ] Port `street`, `facing` and `compass` with golden tests
- [ ] Optional GeoJSON output for `locate` so a map tool can draw the band

## License
MIT (keeps the original geo-sleuth copyright notice)
