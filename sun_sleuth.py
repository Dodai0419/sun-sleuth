#!/usr/bin/env python3
"""Sun geometry for photo geolocation: sun position, shadow ratio, where/when a shadow fits, dish pointing.

Lean, stdlib-only port of geo-sleuth's sun.py (NOAA/Meeus sun position with refraction).
Azimuths are compass bearings (0 = north, clockwise). Times default to UTC; pass --tz or an offset.

  pos     sun azimuth / elevation / shadow at a place and time
  ratio   shadow ratio <-> sun elevation
  locate  known time + elevation (or shadow ratio) and/or shadow bearing -> matching grid points in a bbox
  when    known place + elevation and/or shadow bearing -> matching times of day (or days in a range)
  dish    geostationary dish pointing, or longitude from a dish azimuth

Examples:
  sun_sleuth.py pos --at 39.9042,116.4074 --time 2023-08-15T16:20+08:00
  sun_sleuth.py locate --time 2023-08-15T16:20+08:00 --ratio 1.2 --tol 1.5 --bbox 34,110,42,122
  sun_sleuth.py when --at 30.25,120.16 --dates 2024-01-01:2024-03-31 --elev 40 --shadow-bearing 330
  sun_sleuth.py dish --lat 31.2 --sat 92.2 --azimuth 215
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import date, datetime, timedelta, timezone

_D = math.degrees
_R = math.radians


def _sun_core(dt_utc: datetime) -> tuple[float, float]:
    """(solar declination deg, equation of time in minutes)."""
    jd = dt_utc.timestamp() / 86400 + 2440587.5
    t = (jd - 2451545) / 36525
    l0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360
    m = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    sm, om, rl0 = math.sin(_R(m)), _R(125.04 - 1934.136 * t), _R(l0)  # each reused below: same values, computed once
    c = (sm * (1.914602 - t * (0.004817 + 0.000014 * t))
         + math.sin(_R(2 * m)) * (0.019993 - 0.000101 * t) + math.sin(_R(3 * m)) * 0.000289)
    app_long = l0 + c - 0.00569 - 0.00478 * math.sin(om)
    obliq0 = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
    obliq = obliq0 + 0.00256 * math.cos(om)
    decl = _D(math.asin(math.sin(_R(obliq)) * math.sin(_R(app_long))))
    y = math.tan(_R(obliq / 2)) ** 2
    eqt = 4 * _D(y * math.sin(2 * rl0) - 2 * e * sm
                 + 4 * e * y * sm * math.cos(2 * rl0)
                 - 0.5 * y * y * math.sin(4 * rl0) - 1.25 * e * e * math.sin(2 * _R(m)))
    return decl, eqt


def _refraction(h: float) -> float:
    if h > 85:
        return 0.0
    te = math.tan(_R(h))
    if h > 5:
        r = 58.1 / te - 0.07 / te ** 3 + 0.000086 / te ** 5
    elif h > -0.575:
        r = 1735 + h * (-518.2 + h * (103.4 + h * (-12.79 + h * 0.711)))
    else:
        r = -20.772 / te
    return r / 3600


def _time_terms(dt_utc: datetime) -> tuple[float, float, float]:
    """Everything sun_position needs that depends only on time: (minutes + eqt, sin decl, cos decl)."""
    decl, eqt = _sun_core(dt_utc)
    minutes = dt_utc.hour * 60 + dt_utc.minute + dt_utc.second / 60 + dt_utc.microsecond / 6e7
    return minutes + eqt, math.sin(_R(decl)), math.cos(_R(decl))


def _azimuth(zen, sl, cl, sd, west):
    denom = cl * math.sin(_R(zen))
    if abs(denom) < 1e-9:
        return 180.0
    ca = max(-1.0, min(1.0, (sl * math.cos(_R(zen)) - sd) / denom))
    return (_D(math.acos(ca)) + 180) % 360 if west else (540 - _D(math.acos(ca))) % 360


def sun_position(lat: float, lon: float, dt_utc: datetime) -> tuple[float, float]:
    """(azimuth deg, refracted elevation deg). dt_utc must be timezone-aware UTC."""
    me, sd, cd = _time_terms(dt_utc)
    sl, cl = math.sin(_R(lat)), math.cos(_R(lat))
    tst = (me + 4 * lon) % 1440
    ha = tst / 4 + 180 if tst / 4 < 0 else tst / 4 - 180
    zen = _D(math.acos(max(-1.0, min(1.0, sl * sd + cl * cd * math.cos(_R(ha))))))
    elev = 90 - zen
    return _azimuth(zen, sl, cl, sd, ha > 0), elev + _refraction(elev)


def _cz_bounds(tel, tol):
    """Bounds on cos(zenith) outside which _hit must fail, so callers skip the acos/tan work.
    Refraction adds 0..0.6 deg, so unrefracted elevation < -1 deg can never be > 0, and one more
    than 1 deg outside [tel - tol, tel + tol] can never pass the elevation check."""
    lo = -1.0 if tel is None else max(-1.0, tel - tol - 1)
    hi = math.inf if tel is None or tel + tol + 1 >= 90 else math.sin(_R(tel + tol + 1))
    return math.sin(_R(lo)), hi


def _hit(cz, sl, cl, sd, west, tel, tol, taz, az_tol, need_az):
    """Exact upstream match test for one (place, time): (azimuth, elevation) or None."""
    zen = _D(math.acos(max(-1.0, min(1.0, cz))))
    el = 90 - zen
    el += _refraction(el)
    if el <= 0 or (tel is not None and abs(el - tel) > tol):
        return None
    az = _azimuth(zen, sl, cl, sd, west) if need_az else None
    if taz is not None and _ang_diff(az, taz) > az_tol:
        return None
    return az, el


def subsolar_point(dt_utc: datetime) -> tuple[float, float]:
    decl, eqt = _sun_core(dt_utc)
    minutes = dt_utc.hour * 60 + dt_utc.minute + dt_utc.second / 60
    lon = -(minutes + eqt - 720) / 4
    return decl, (lon + 540) % 360 - 180


def shadow_ratio(elev: float) -> float:
    return math.inf if elev <= 0 else 1 / math.tan(_R(elev))


def elev_from_ratio(ratio: float) -> float:
    return _D(math.atan(1 / ratio))


def _ang_diff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


_RE, _RGEO = 6378.137, 42164.0


def dish_pointing(lat: float, lon: float, sat_lon: float) -> tuple[float, float]:
    la, lo = _R(lat), _R(lon)
    gx, gy, gz = _RE * math.cos(la) * math.cos(lo), _RE * math.cos(la) * math.sin(lo), _RE * math.sin(la)
    sx, sy, sz = _RGEO * math.cos(_R(sat_lon)), _RGEO * math.sin(_R(sat_lon)), 0.0
    dx, dy, dz = sx - gx, sy - gy, sz - gz
    east = -math.sin(lo) * dx + math.cos(lo) * dy
    north = -math.sin(la) * math.cos(lo) * dx - math.sin(la) * math.sin(lo) * dy + math.cos(la) * dz
    up = math.cos(la) * math.cos(lo) * dx + math.cos(la) * math.sin(lo) * dy + math.sin(la) * dz
    return (_D(math.atan2(east, north)) + 360) % 360, _D(math.atan2(up, math.hypot(east, north)))


# ---------------------------------------------------------------- input parsing

def _pair(s: str) -> tuple[float, float]:
    a, b = s.split(",")
    return float(a), float(b)


def _zone(tz: str):
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        return ZoneInfo(tz)
    except ZoneInfoNotFoundError:
        sys.exit(f"Unknown time zone {tz!r} (on Windows run `pip install tzdata`, or put an offset in --time like +08:00)")


def _to_utc(s: str, tz: str | None) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_zone(tz) if tz else timezone.utc)
    return dt.astimezone(timezone.utc)


def _targets(args) -> tuple[float | None, float | None]:
    tel = elev_from_ratio(args.ratio) if args.ratio is not None else args.elev
    taz = (args.shadow_bearing + 180) % 360 if args.shadow_bearing is not None else args.sun_azimuth
    if tel is None and taz is None:
        sys.exit("Need at least one of --elev / --ratio or --shadow-bearing / --sun-azimuth")
    return tel, taz


# ---------------------------------------------------------------- subcommands

def cmd_pos(args) -> None:
    lat, lon = args.at
    t = _to_utc(args.time, args.tz)
    az, el = sun_position(lat, lon, t)
    ss = subsolar_point(t)
    print(json.dumps({
        "utc": t.isoformat(timespec="minutes"), "sun_azimuth": round(az, 2), "sun_elevation": round(el, 2),
        "shadow_len_per_1m": None if el <= 0 else round(shadow_ratio(el), 3),
        "shadow_bearing": round((az + 180) % 360, 1), "subsolar_point": [round(ss[0], 3), round(ss[1], 3)],
    }, ensure_ascii=False))


def cmd_ratio(args) -> None:
    if args.shadow is not None:
        print(f"Shadow ratio 1:{args.shadow} → sun elevation angle {elev_from_ratio(args.shadow):.2f}°")
    else:
        print(f"Sun elevation angle {args.elev}° → shadow length of a 1 m object {shadow_ratio(args.elev):.3f} m")


def cmd_locate(args) -> None:
    tel, taz = _targets(args)
    tol, az_tol, want_az = args.tol, args.az_tol, taz is not None
    t0 = _to_utc(args.time, args.tz)
    k = max(0, int(args.time_tol // 5))
    times = [t0 + timedelta(minutes=5 * i) for i in range(-k, k + 1)] if args.time_tol else [t0]
    terms = [_time_terms(t) for t in times]  # time-only terms: once, not once per grid point
    s, w, n, e = args.bbox
    step = args.step
    cols, lon = [], w  # same repeated-addition grid as upstream, so points match exactly
    while lon <= e + 1e-9:
        has = []  # hour angle depends on (lon, time) only, so its cosine is shared by every latitude
        for me, _, _ in terms:
            tst = (me + 4 * lon) % 1440
            ha = tst / 4 + 180 if tst / 4 < 0 else tst / 4 - 180
            has.append((math.cos(_R(ha)), ha > 0))
        cols.append((lon, has))
        lon += step
    cz_lo, cz_hi = _cz_bounds(tel, tol)
    pts = []
    lat = s
    while lat <= n + 1e-9:
        sl, cl = math.sin(_R(lat)), math.cos(_R(lat))
        row = [(sl * sd, cl * cd, sd) for _, sd, cd in terms]
        for lon, has in cols:
            for (ssd, ccd, sd), (cosha, west) in zip(row, has):
                cz = ssd + ccd * cosha
                if cz_lo <= cz <= cz_hi and _hit(cz, sl, cl, sd, west, tel, tol, taz, az_tol, want_az):
                    pts.append((round(lat, 4), round(lon, 4)))
                    break
        lat += step
    ss = subsolar_point(t0)
    out = {"utc": t0.isoformat(timespec="minutes"), "target_elev": None if tel is None else round(tel, 2),
           "target_sun_azimuth": None if taz is None else round(taz, 1), "subsolar_point": [round(ss[0], 3), round(ss[1], 3)],
           "equal_elev_circle_radius_km": None if tel is None else round((90 - tel) * 111.195, 0),
           "grid_step_deg": step, "matched_points": len(pts)}
    if pts:
        lats, lns = [p[0] for p in pts], [p[1] for p in pts]
        out["matched_bbox"] = [min(lats), min(lns), max(lats), max(lns)]
        cols: dict[float, list[float]] = {}
        for la, lo in pts:
            cols.setdefault(round(lo, 2), []).append(la)
        every = max(1, len(cols) // 12)
        out["lat_range_by_lon"] = {f"{lo:.2f}": [min(v), max(v)] for i, (lo, v) in enumerate(sorted(cols.items())) if i % every == 0}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    if args.points:
        with open(args.points, "w", encoding="utf-8") as f:
            f.write(json.dumps({f"p{i}": list(p) for i, p in enumerate(pts)}))
        print(f"points -> {args.points}")


def _scan_day(lat, lon, day: date, tz, tel, tol, taz, az_tol, step_min: int):
    """Matching windows of one day: [(start, end, mid azimuth, mid elevation)]."""
    sl, cl, lon4 = math.sin(_R(lat)), math.cos(_R(lat)), 4 * lon
    cz_lo, cz_hi = _cz_bounds(tel, tol)
    start = datetime(day.year, day.month, day.day, tzinfo=tz)
    wins, cur = [], None
    for i in range(0, 24 * 60, step_min):
        lt = start + timedelta(minutes=i)
        me, sd, cd = _time_terms(lt.astimezone(timezone.utc))
        tst = (me + lon4) % 1440
        ha = tst / 4 + 180 if tst / 4 < 0 else tst / 4 - 180
        cz = sl * sd + cl * cd * math.cos(_R(ha))
        hit = cz_lo <= cz <= cz_hi and _hit(cz, sl, cl, sd, ha > 0, tel, tol, taz, az_tol, True)
        if hit:
            cur = [lt, lt, []] if cur is None else [cur[0], lt, cur[2]]
            cur[2].append(hit)
        elif cur is not None:
            wins.append(cur)
            cur = None
    if cur is not None:
        wins.append(cur)
    return [(a, b, *vals[len(vals) // 2]) for a, b, vals in wins]


def cmd_when(args) -> None:
    tel, taz = _targets(args)
    tz = _zone(args.tz) if args.tz else timezone.utc
    lat, lon = args.at
    if args.dates:
        a, b = (date.fromisoformat(x) for x in args.dates.split(":"))
        days = [a + timedelta(days=i) for i in range((b - a).days + 1)]
    else:
        days = [date.fromisoformat(args.date)]
    hits = 0
    for d in days:
        for s, e, az, el in _scan_day(lat, lon, d, tz, tel, args.tol, taz, args.az_tol, args.step_min):
            hits += 1
            mid = s + (e - s) / 2
            _, e1 = sun_position(lat, lon, (mid - timedelta(minutes=5)).astimezone(timezone.utc))
            _, e2 = sun_position(lat, lon, (mid + timedelta(minutes=5)).astimezone(timezone.utc))
            rate = abs(e2 - e1) / 10
            sens = f"  elevation angle changes {rate:.2f}° per minute, 1° off ≈ {1 / rate:.0f} minutes" if rate > 1e-3 else "  elevation angle barely changes around noon; time resolution is poor"
            print(f"{d} {s:%H:%M}–{e:%H:%M}  sun azimuth {az:5.1f}°  elevation {el:4.1f}°  shadow bearing {(az + 180) % 360:5.1f}°  "
                  f"shadow ratio 1:{shadow_ratio(el):.2f}{sens}")
    if not hits:
        print("No matching times (loosen --tol / --az-tol, or check whether the time zone or bearing is backwards)")


def cmd_dish(args) -> None:
    sat = args.sat
    if args.at:
        lat, lon = args.at
        az, el = dish_pointing(lat, lon, sat)
        print(f"Place {lat},{lon} pointing at the satellite at longitude {sat}°E: azimuth {az:.1f}°, elevation angle {el:.1f}°")
        return
    if args.azimuth is None or args.lat is None:
        sys.exit("Forward calculation: give --at; working back to longitude: give --lat and --azimuth")
    best = []
    for i in range(-1800, 1801):
        lon = i / 10
        az, el = dish_pointing(args.lat, lon, sat)
        if el > 0 and _ang_diff(az, args.azimuth) <= args.az_tol:
            best.append((lon, az, el))
    if not best:
        print("No longitude at this latitude matches (the dish may point at a different satellite)")
        return
    print(f"Latitude {args.lat}, dish azimuth {args.azimuth}±{args.az_tol}° to the satellite at longitude {sat}°E → longitude range {best[0][0]}° ~ {best[-1][0]}°, "
          f"elevation angle about {best[len(best) // 2][2]:.0f}°")


def _neg_coords(argv: list[str]) -> list[str]:
    """argparse reads -1.45,-48.5 as an option; a leading space keeps it a value (float() ignores it)."""
    return [" " + a if re.match(r"^-\d[\d.]*(,-?[\d.]+)+$", a) else a for a in argv]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pos", help="sun position at a place and time")
    p.add_argument("--at", type=_pair, required=True, help="lat,lon")
    p.add_argument("--time", required=True, help="2024-06-06T15:39, may include +08:00")
    p.add_argument("--tz", help="IANA time zone, e.g. Asia/Shanghai")
    r = sub.add_parser("ratio", help="shadow ratio <-> elevation")
    g = r.add_mutually_exclusive_group(required=True)
    g.add_argument("--shadow", type=float, help="shadow length of a 1 m object")
    g.add_argument("--elev", type=float)
    lo = sub.add_parser("locate", help="known time -> grid points matching the sun")
    w = sub.add_parser("when", help="known place -> matching times / dates")
    for sp in (lo, w):
        sp.add_argument("--elev", type=float, help="sun elevation deg")
        sp.add_argument("--ratio", type=float, help="shadow ratio (shadow of a 1 m object); instead of --elev")
        sp.add_argument("--tol", type=float, default=2.0, help="elevation tolerance deg, default 2")
        sp.add_argument("--shadow-bearing", type=float, help="bearing deg from object to shadow tip")
        sp.add_argument("--sun-azimuth", type=float, help="sun azimuth deg; instead of --shadow-bearing")
        sp.add_argument("--az-tol", type=float, default=10.0, help="azimuth tolerance deg, default 10")
        sp.add_argument("--tz")
    lo.add_argument("--time", required=True)
    lo.add_argument("--time-tol", type=float, default=0, help="capture-time uncertainty in minutes (+/-)")
    lo.add_argument("--bbox", type=lambda s: tuple(map(float, s.split(","))), required=True, help="south,west,north,east")
    lo.add_argument("--step", type=float, default=0.1, help="grid step deg, default 0.1 (~11 km)")
    lo.add_argument("--points", help="write matching points as {name:[lat,lon]}")
    w.add_argument("--at", type=_pair, required=True)
    dg = w.add_mutually_exclusive_group(required=True)
    dg.add_argument("--date", help="single day 2024-10-01")
    dg.add_argument("--dates", help="range 2024-01-01:2024-12-31")
    w.add_argument("--step-min", type=int, default=2)
    d = sub.add_parser("dish", help="dish pointing / longitude from dish azimuth")
    d.add_argument("--sat", type=float, default=92.2, help="satellite longitude, default ChinaSat-9 92.2")
    d.add_argument("--at", type=_pair, help="lat,lon: forward")
    d.add_argument("--lat", type=float, help="inverse: known latitude")
    d.add_argument("--azimuth", type=float, help="inverse: dish azimuth")
    d.add_argument("--az-tol", type=float, default=5.0)
    args = ap.parse_args(_neg_coords(sys.argv[1:] if argv is None else argv))
    {"pos": cmd_pos, "ratio": cmd_ratio, "locate": cmd_locate, "when": cmd_when, "dish": cmd_dish}[args.cmd](args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    main()
