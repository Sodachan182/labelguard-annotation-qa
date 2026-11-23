"""Polygon topology checks built on Shapely."""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass

from shapely import validation
from shapely.geometry import Polygon


@dataclass(frozen=True)
class PolygonDiagnosis:
    vertex_count: int
    distinct_vertices: int
    repeated_consecutive: int
    area: float
    hull_area: float
    is_valid: bool
    invalid_reason: str
    self_intersection_at: tuple[float, float] | None


def distinct_vertices(ring: Sequence[Sequence[float]]) -> int:
    return len({(round(p[0], 6), round(p[1], 6)) for p in ring})


def repeated_consecutive(ring: Sequence[Sequence[float]]) -> int:
    """Count consecutive duplicate vertices, including last -> first wrap-around
    only when the ring is not explicitly closed."""
    n = 0
    for a, b in itertools.pairwise(ring):
        if math.isclose(a[0], b[0]) and math.isclose(a[1], b[1]):
            n += 1
    return n


def shoelace_area(ring: Sequence[Sequence[float]]) -> float:
    s = 0.0
    for (x1, y1), (x2, y2) in zip(ring, [*list(ring[1:]), ring[0]], strict=False):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def diagnose(ring: Sequence[Sequence[float]]) -> PolygonDiagnosis:
    pts = [(float(p[0]), float(p[1])) for p in ring]
    # Drop explicit closing vertex before counting.
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    distinct = distinct_vertices(pts)
    repeats = repeated_consecutive(pts)
    if distinct < 3:
        return PolygonDiagnosis(len(pts), distinct, repeats, 0.0, 0.0, False, "Too few points", None)
    poly = Polygon(pts)
    reason = validation.explain_validity(poly)
    valid = poly.is_valid
    location = None
    if not valid and "[" in reason:
        try:
            coords = reason[reason.index("[") + 1 : reason.index("]")].split()
            location = (float(coords[0]), float(coords[1]))
        except (ValueError, IndexError):
            location = None
    return PolygonDiagnosis(
        vertex_count=len(pts),
        distinct_vertices=distinct,
        repeated_consecutive=repeats,
        area=shoelace_area(pts),
        hull_area=poly.convex_hull.area,
        is_valid=valid,
        invalid_reason="" if valid else reason.split("[")[0].strip(),
        self_intersection_at=location,
    )
