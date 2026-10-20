
# sun-sleuth

Sun geometry for photo geolocation. One stdlib Python file: `sun_sleuth.py` (run from the repo root).
Azimuths are compass bearings (0 = north, clockwise). Times are UTC unless `--time` carries an offset (`+08:00`) or `--tz` names an IANA zone (needs `tzdata` on Windows).

## Measure first
- Shadow ratio = shadow length / object height. Sun elevation = atan(1 / ratio): `python sun_sleuth.py ratio --shadow 1.2`
- Shadow bearing = compass direction from the object to the shadow tip (sun azimuth + 180).

## Commands
- Sun at a place and time: `python sun_sleuth.py pos --at LAT,LON --time 2023-08-15T16:20+08:00`
- Where could it be (time known): `python sun_sleuth.py locate --time 2023-08-15T16:20+08:00 --ratio 1.2 --tol 1.5 --shadow-bearing 60 --az-tol 10 --bbox S,W,N,E [--step 0.1] [--time-tol 30] [--points out.json]`
- When could it be (place known): `python sun_sleuth.py when --at LAT,LON --date 2024-10-01 --elev 40 --shadow-bearing 330` or `--dates 2024-01-01:2024-12-31`
- Dish pointing: `python sun_sleuth.py dish --at LAT,LON --sat 92.2`; longitude from a dish azimuth: `python sun_sleuth.py dish --lat 31.2 --azimuth 215`

## Rules
- Give at least one of `--elev`/`--ratio` and `--shadow-bearing`/`--sun-azimuth` to `locate` and `when`.
- Negative coordinates work as-is (`--at -1.45,-48.5`).
- Widen `--tol` / `--az-tol` before concluding "no match"; a measured ratio is rarely better than ±1.5°.
- A `locate` band is a hypothesis: confirm with other clues (signs, plates, terrain) before reporting a place.
