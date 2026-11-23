"""Polygon rules (POL), using Shapely for topology."""

from __future__ import annotations

from collections.abc import Iterator

from labelguard.geometry.polygons import diagnose
from labelguard.models import Annotation, IssueKind, QualityIssue, Severity
from labelguard.validation.engine import (
    Rule,
    RuleContext,
    classify_parse_error,
    finite,
    register,
)


def _rings(ctx: RuleContext) -> Iterator[tuple[Annotation, int, list[list[float]]]]:
    for ann in ctx.dataset.annotations:
        if ann.outside:
            continue
        for idx, ring in enumerate(ann.polygons):
            if ring and all(len(p) == 2 and finite(p) for p in ring):
                yield ann, idx, ring


def _part(ann: Annotation, idx: int) -> str:
    return f" (part {idx + 1} of {len(ann.polygons)})" if len(ann.polygons) > 1 else ""


@register
class TooFewVertices(Rule):
    id = "POL001"
    name = "Too few vertices"
    group = "Polygons"
    kind = IssueKind.STRUCTURAL
    severity = Severity.CRITICAL
    description = "A polygon needs at least three distinct vertices to enclose an area."
    action = "Redraw the polygon or delete it."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        for ann, idx, ring in _rings(ctx):
            d = diagnose(ring)
            if d.distinct_vertices < 3:
                yield self.issue(
                    ctx,
                    annotation=ann,
                    title=f"Polygon has {d.distinct_vertices} distinct vertices{_part(ann, idx)}",
                    description=f"{d.vertex_count} points given, {d.distinct_vertices} distinct.",
                    evidence={"points": ring, "distinct": d.distinct_vertices},
                    key=str(idx),
                )


@register
class SelfIntersection(Rule):
    id = "POL002"
    name = "Self-intersecting polygon"
    group = "Polygons"
    kind = IssueKind.STRUCTURAL
    severity = Severity.CRITICAL
    description = "Edges of the polygon cross each other, so its inside is undefined."
    action = "Reorder or move the crossing vertices so the outline does not cross itself."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        for ann, idx, ring in _rings(ctx):
            d = diagnose(ring)
            if d.hull_area > 1e-6 and "self-intersection" in d.invalid_reason.lower():
                at = d.self_intersection_at
                where = f" near ({at[0]:.1f}, {at[1]:.1f})" if at else ""
                yield self.issue(
                    ctx,
                    annotation=ann,
                    title=f"Polygon crosses itself{where}{_part(ann, idx)}",
                    description=f"Shapely reports: {d.invalid_reason}{where}.",
                    evidence={"reason": d.invalid_reason, "location": at, "points": ring},
                    key=str(idx),
                )


@register
class ZeroAreaPolygon(Rule):
    id = "POL003"
    name = "Zero-area polygon"
    group = "Polygons"
    kind = IssueKind.STRUCTURAL
    severity = Severity.CRITICAL
    description = "All vertices are collinear; the polygon encloses no area."
    action = "Redraw the polygon around the object."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        for ann, idx, ring in _rings(ctx):
            d = diagnose(ring)
            if d.distinct_vertices >= 3 and d.hull_area < 1e-6:
                yield self.issue(
                    ctx,
                    annotation=ann,
                    title=f"Polygon has zero area{_part(ann, idx)}",
                    description=f"{d.distinct_vertices} distinct vertices, all on one line.",
                    evidence={"area": d.area, "points": ring},
                    key=str(idx),
                )


@register
class RepeatedVertices(Rule):
    id = "POL004"
    name = "Repeated consecutive vertices"
    group = "Polygons"
    kind = IssueKind.STRUCTURAL
    severity = Severity.WARNING
    description = "The same vertex appears twice in a row, creating a zero-length edge."
    action = "Remove the repeated vertex; some rasterizers mis-handle zero-length edges."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        for ann, idx, ring in _rings(ctx):
            d = diagnose(ring)
            if d.repeated_consecutive and d.distinct_vertices >= 3:
                yield self.issue(
                    ctx,
                    annotation=ann,
                    title=f"{d.repeated_consecutive} repeated vertex(es){_part(ann, idx)}",
                    description=f"{d.repeated_consecutive} zero-length edge(s) in a {d.vertex_count}-point polygon.",
                    evidence={"repeated": d.repeated_consecutive, "points": ring},
                    key=str(idx),
                )


@register
class OutOfBoundsPolygon(Rule):
    id = "POL005"
    name = "Polygon outside image"
    group = "Polygons"
    kind = IssueKind.STRUCTURAL
    severity = Severity.CRITICAL
    description = "One or more vertices lie outside the image frame beyond the tolerance."
    action = "Move the vertices onto the image edge."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        tol = ctx.config.polygons.bounds_tolerance_px
        for ann, idx, ring in _rings(ctx):
            size = ctx.image_size(ann)
            if size is None:
                continue
            w, h = size
            outside = [
                (i, p) for i, p in enumerate(ring) if p[0] < -tol or p[1] < -tol or p[0] > w + tol or p[1] > h + tol
            ]
            if outside:
                yield self.issue(
                    ctx,
                    annotation=ann,
                    title=f"{len(outside)} vertex(es) outside the image{_part(ann, idx)}",
                    description=f"Image is {w:g} × {h:g}; first offending vertex "
                    f"#{outside[0][0]} at ({outside[0][1][0]:g}, {outside[0][1][1]:g}).",
                    evidence={"image_size": [w, h], "vertices": [i for i, _ in outside], "points": ring},
                    key=str(idx),
                )


@register
class TinyPolygon(Rule):
    id = "POL006"
    name = "Suspiciously small polygon"
    group = "Polygons"
    kind = IssueKind.HEURISTIC
    severity = Severity.WARNING
    description = "Polygon area is below the configured minimum."
    action = "Check whether the polygon is a real small object or a stray click."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        limit = ctx.config.polygons.min_area_px
        for ann, idx, ring in _rings(ctx):
            d = diagnose(ring)
            if d.distinct_vertices >= 3 and 1e-6 <= d.area < limit and d.is_valid:
                yield self.issue(
                    ctx,
                    annotation=ann,
                    title=f"Polygon area is {d.area:.0f} px²{_part(ann, idx)}",
                    description=f"Below the {limit:g} px² minimum.",
                    evidence={"area": d.area, "limit": limit},
                    key=str(idx),
                )


@register
class MalformedPolygon(Rule):
    id = "POL007"
    name = "Malformed polygon"
    group = "Polygons"
    kind = IssueKind.STRUCTURAL
    severity = Severity.CRITICAL
    description = "The polygon's coordinate list cannot be read as x,y pairs."
    action = "Re-export the polygon; the coordinate list is truncated or corrupted."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        for ann in ctx.dataset.annotations:
            if not ann.polygons and ann.geometry_type.value != "polygon":
                continue
            errs = [
                e
                for e in ann.parse_errors
                if classify_parse_error(e) == "structure" and "must be [" not in e and "keypoints" not in e
            ]
            if errs:
                yield self.issue(
                    ctx,
                    annotation=ann,
                    title="Polygon coordinates are malformed",
                    description="; ".join(errs).capitalize() + ".",
                    evidence={"errors": errs},
                )
