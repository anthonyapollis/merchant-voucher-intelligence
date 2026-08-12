"""
build_geo.py
============
Prepares the geographic layer.

Source geometry is Natural Earth admin-1 boundaries for South Africa, reused
from the PargoParcels repo (data/reference/za_provinces.geojson). Real
boundaries, not hand-drawn shapes - a map with invented coastlines is worse
than no map, because it looks authoritative.

Two outputs:

  data/reference/za_provinces.geojson            the source, copied in so this
                                                 project stands alone
  data/reference/za_provinces_simplified.json    ring coordinates simplified
                                                 with Ramer-Douglas-Peucker,
                                                 plus centroid, area and the
                                                 projected bounding box

Simplification matters here because the map is embedded in a single offline
HTML file. The full geometry is 185 KB of coordinates for a map that renders
about 600 pixels wide, where most of that precision is well under a pixel.

Run:  python build/build_geo.py
"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "data" / "reference"
SOURCE = Path(
    r"C:\Users\Anthony.DESKTOP-ES5HL78\Downloads\pargo files\PargoParcels_Portfolio"
    r"\PargoParcels\data\reference\za_provinces.geojson"
)

# Degrees. At South Africa's extent (~13 degrees of longitude) rendered around
# 600px wide, one pixel is roughly 0.022 degrees, so this keeps the error to
# about half a pixel.
EPSILON = 0.012


def perpendicular_distance(pt, start, end) -> float:
    (x, y), (x1, y1), (x2, y2) = pt, start, end
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(x - x1, y - y1)
    # Distance from the point to the infinite line through start and end.
    return abs(dy * x - dx * y + x2 * y1 - y2 * x1) / math.hypot(dx, dy)


def rdp(points: list, epsilon: float) -> list:
    """Ramer-Douglas-Peucker. Keeps the points that carry the shape."""
    if len(points) < 3:
        return points
    dmax, index = 0.0, 0
    for i in range(1, len(points) - 1):
        d = perpendicular_distance(points[i], points[0], points[-1])
        if d > dmax:
            dmax, index = d, i
    if dmax <= epsilon:
        return [points[0], points[-1]]
    left = rdp(points[:index + 1], epsilon)
    right = rdp(points[index:], epsilon)
    return left[:-1] + right


def ring_area(ring: list) -> float:
    """Shoelace, in square degrees. Used only to rank rings by size."""
    a = 0.0
    for i in range(len(ring)):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % len(ring)]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2


EARTH_RADIUS_KM = 6371.0088


def geodesic_area_km2(ring: list) -> float:
    """Spherical polygon area.

    Natural Earth ships area_sqkm as 0 for every South African province, so the
    figure is computed from the geometry rather than trusted from the file. A
    planar shoelace on lon/lat would overstate area badly at 30 degrees south,
    because a degree of longitude there is only ~87% of a degree at the equator.
    """
    total = 0.0
    for i in range(len(ring)):
        lon1, lat1 = math.radians(ring[i][0]), math.radians(ring[i][1])
        lon2, lat2 = (math.radians(ring[(i + 1) % len(ring)][0]),
                      math.radians(ring[(i + 1) % len(ring)][1]))
        total += (lon2 - lon1) * (2 + math.sin(lat1) + math.sin(lat2))
    return abs(total * EARTH_RADIUS_KM ** 2 / 2)


def main() -> None:
    REF.mkdir(parents=True, exist_ok=True)
    if not SOURCE.exists():
        raise SystemExit(f"Source geometry not found: {SOURCE}")
    local_copy = REF / "za_provinces.geojson"
    if not local_copy.exists():
        shutil.copy2(SOURCE, local_copy)

    gj = json.loads(local_copy.read_text(encoding="utf8"))

    provinces = []
    pts_before = pts_after = 0
    for feat in gj["features"]:
        p, geom = feat["properties"], feat["geometry"]
        polys = (geom["coordinates"] if geom["type"] == "MultiPolygon"
                 else [geom["coordinates"]])

        # Area comes from the FULL geometry, before simplification - the map
        # can lose half a pixel of coastline, the statistic should not.
        area_km2 = sum(geodesic_area_km2([tuple(c[:2]) for c in poly[0]])
                       for poly in polys)

        rings = []
        for poly in polys:
            outer = [tuple(c[:2]) for c in poly[0]]  # exterior ring only
            pts_before += len(outer)
            simple = rdp(outer, EPSILON)
            # A ring reduced below four points has collapsed; drop it rather
            # than draw a triangle where an island used to be.
            if len(simple) >= 4:
                rings.append({"pts": [[round(x, 4), round(y, 4)] for x, y in simple],
                              "area": ring_area(simple)})
                pts_after += len(simple)

        # Tiny offshore islands add points and nothing readable at this size.
        biggest = max(r["area"] for r in rings)
        rings = [r for r in rings if r["area"] >= biggest * 0.01]

        provinces.append({
            "name": p["name"],
            "code": p.get("postal") or p.get("code_hasc", "").split(".")[-1],
            "areaSqKm": round(area_km2, 0),
            "lat": round(float(p["latitude"]), 4),
            "lon": round(float(p["longitude"]), 4),
            "rings": [r["pts"] for r in sorted(rings, key=lambda r: -r["area"])],
        })

    xs = [x for pr in provinces for ring in pr["rings"] for x, _ in ring]
    ys = [y for pr in provinces for ring in pr["rings"] for _, y in ring]
    out = {
        "source": "Natural Earth admin-1 states and provinces (public domain)",
        "simplification": f"Ramer-Douglas-Peucker, epsilon {EPSILON} degrees",
        "bbox": [round(min(xs), 4), round(min(ys), 4),
                 round(max(xs), 4), round(max(ys), 4)],
        "provinces": sorted(provinces, key=lambda p: p["name"]),
    }
    target = REF / "za_provinces_simplified.json"
    target.write_text(json.dumps(out, separators=(",", ":")), encoding="utf8")

    print(f"{len(provinces)} provinces")
    print(f"  points {pts_before:,} -> {pts_after:,} "
          f"({pts_after / pts_before:.0%} kept)")
    print(f"  {local_copy.stat().st_size / 1024:,.0f} KB -> "
          f"{target.stat().st_size / 1024:,.0f} KB")
    print(f"  bbox {out['bbox']}")
    for pr in out["provinces"]:
        print(f"    {pr['name']:<16} {len(pr['rings'])} ring(s), "
              f"{sum(len(r) for r in pr['rings'])} pts, "
              f"{pr['areaSqKm']:,.0f} km2")


if __name__ == "__main__":
    main()
