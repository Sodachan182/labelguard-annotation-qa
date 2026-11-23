"""Keypoint / point rules (KPT).

COCO visibility: 0 = not labelled (coordinates meaningless), 1 = labelled but
occluded, 2 = labelled and visible. Only labelled points are bounds-checked.
"""

from __future__ import annotations

from collections.abc import Iterator

from labelguard.geometry import boxes as B
from labelguard.models import Annotation, GeometryType, IssueKind, QualityIssue, Severity
from labelguard.validation.engine import (
    Rule,
    RuleContext,
    classify_parse_error,
    finite,
    register,
)

_KP_TYPES = (GeometryType.KEYPOINTS, GeometryType.POINTS)


def _kp_annotations(ctx: RuleContext) -> Iterator[Annotation]:
    for ann in ctx.dataset.annotations:
        if ann.geometry_type in _KP_TYPES and not ann.outside:
            yield ann


def _names(ctx: RuleContext, ann: Annotation) -> list[str]:
    names = ann.raw.get("keypoint_names") or []
    if not names:
        for c in ctx.dataset.categories:
            if c.name == ann.category and c.keypoint_names:
                return list(c.keypoint_names)
    return list(names)


def _labelled(ann: Annotation) -> Iterator[tuple[int, list[float]]]:
    for i, p in enumerate(ann.points):
        v = ann.keypoint_visibility[i] if i < len(ann.keypoint_visibility) else 2
        if v > 0 and len(p) == 2 and finite(p):
            yield i, p


@register
class KeypointOutOfBounds(Rule):
    id = "KPT001"
    name = "Keypoint outside image"
    group = "Keypoints"
    kind = IssueKind.STRUCTURAL
    severity = Severity.CRITICAL
    description = "A labelled point lies outside the image frame."
    action = "Move the point onto the object or mark it as not labelled (v=0)."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        tol = ctx.config.keypoints.bounds_tolerance_px
        for ann in _kp_annotations(ctx):
            size = ctx.image_size(ann)
            if size is None:
                continue
            w, h = size
            names = _names(ctx, ann)
            bad = [(i, p) for i, p in _labelled(ann) if p[0] < -tol or p[1] < -tol or p[0] > w + tol or p[1] > h + tol]
            if bad:
                label = ", ".join(names[i] if i < len(names) else f"#{i}" for i, _ in bad[:4])
                yield self.issue(
                    ctx,
                    annotation=ann,
                    title=f"{len(bad)} point(s) outside the image",
                    description=f"Image is {w:g} × {h:g}; out-of-frame: {label}.",
                    evidence={
                        "image_size": [w, h],
                        "points": {names[i] if i < len(names) else str(i): p for i, p in bad},
                    },
                )


@register
class MalformedKeypoints(Rule):
    id = "KPT002"
    name = "Malformed keypoints"
    group = "Keypoints"
    kind = IssueKind.STRUCTURAL
    severity = Severity.CRITICAL
    description = "The keypoint array is not (x, y, v) triplets, or a visibility flag is not 0, 1 or 2."
    action = "Re-export the keypoints; the array is truncated or has invalid flags."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        for ann in ctx.dataset.annotations:
            if ann.geometry_type not in _KP_TYPES:
                continue
            errs = [
                e
                for e in ann.parse_errors
                if classify_parse_error(e) == "structure" and "segmentation" not in e and "must be [" not in e
            ]
            bad_v = [v for v in ann.keypoint_visibility if v not in (0, 1, 2)]
            if bad_v:
                errs.append(f"visibility flags {sorted(set(bad_v))} are not 0, 1 or 2")
            if errs:
                yield self.issue(
                    ctx,
                    annotation=ann,
                    title="Keypoints are malformed",
                    description="; ".join(errs).capitalize() + ".",
                    evidence={"errors": errs},
                )


@register
class KeypointCount(Rule):
    id = "KPT003"
    name = "Keypoint count mismatch"
    group = "Keypoints"
    kind = IssueKind.STRUCTURAL
    severity = Severity.CRITICAL
    description = "The number of points differs from the category's keypoint schema."
    action = "Add the missing points (use v=0 when not visible) or fix the schema."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        override = ctx.config.keypoints.expected_count
        for ann in ctx.dataset.annotations:
            if ann.geometry_type != GeometryType.KEYPOINTS and not (
                override and ann.geometry_type == GeometryType.POINTS
            ):
                continue
            if any("keypoints" in e and classify_parse_error(e) == "structure" for e in ann.parse_errors):
                continue  # reported once by KPT002; the count is meaningless here
            expected = override
            if expected is None:
                for c in ctx.dataset.categories:
                    if c.name == ann.category and c.keypoint_names:
                        expected = len(c.keypoint_names)
            if expected and len(ann.points) != expected:
                yield self.issue(
                    ctx,
                    annotation=ann,
                    title=f"{len(ann.points)} keypoints, schema expects {expected}",
                    description=f"Category '{ann.category}' defines {expected} keypoints.",
                    evidence={"count": len(ann.points), "expected": expected},
                )


@register
class SuspiciousKeypointPosition(Rule):
    id = "KPT004"
    name = "Suspicious keypoint position"
    group = "Keypoints"
    kind = IssueKind.HEURISTIC
    severity = Severity.WARNING
    description = (
        "A keypoint lies well outside its own object box, or violates a configured "
        "left/right ordering rule (possible mirrored labels)."
    )
    action = "Check whether the point belongs to this object and whether left/right are swapped."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        t = ctx.config.keypoints
        for ann in _kp_annotations(ctx):
            names = _names(ctx, ann)
            pts = dict(_labelled(ann))
            if ann.bbox is not None and B.is_finite(ann.bbox):
                x1, y1, x2, y2 = ann.bbox
                mx, my = (x2 - x1) * t.bbox_margin_ratio, (y2 - y1) * t.bbox_margin_ratio
                far = [
                    i for i, p in pts.items() if p[0] < x1 - mx or p[0] > x2 + mx or p[1] < y1 - my or p[1] > y2 + my
                ]
                if far:
                    label = ", ".join(names[i] if i < len(names) else f"#{i}" for i in far[:4])
                    yield self.issue(
                        ctx,
                        annotation=ann,
                        title=f"{len(far)} keypoint(s) far outside the object box",
                        description=f"{label} lie more than {t.bbox_margin_ratio:.0%} of the box "
                        "size outside the annotation's own box.",
                        evidence={"points": {str(i): pts[i] for i in far}, "box_xyxy": ann.bbox},
                        key="box",
                    )
            index = {n: i for i, n in enumerate(names)}
            for a, b in t.order_rules:
                if a in index and b in index and index[a] in pts and index[b] in pts:
                    pa, pb = pts[index[a]], pts[index[b]]
                    if pa[0] >= pb[0]:
                        yield self.issue(
                            ctx,
                            annotation=ann,
                            title=f"'{a}' is not left of '{b}'",
                            description=f"Expected x({a}) < x({b}) for a camera-facing subject; "
                            f"got {pa[0]:.1f} ≥ {pb[0]:.1f}. Labels may be mirrored.",
                            evidence={a: pa, b: pb},
                            key=f"order:{a}:{b}",
                        )
