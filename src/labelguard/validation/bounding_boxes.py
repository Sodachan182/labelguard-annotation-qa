"""Bounding-box rules (BOX).

Heuristic rules (tiny, aspect, duplicate, conflict) only run on boxes that are
structurally sound, so one defect produces one finding rather than a cascade.
Shapes marked ``outside`` in CVAT video are ignored: CVAT keeps stale
coordinates on them by design.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator

import numpy as np

from labelguard.geometry import boxes as B
from labelguard.models import Annotation, IssueKind, QualityIssue, Severity
from labelguard.validation.engine import Rule, RuleContext, register


def _boxes(ctx: RuleContext) -> Iterator[Annotation]:
    for ann in ctx.dataset.annotations:
        if ann.bbox is not None and not ann.outside and B.is_finite(ann.bbox):
            yield ann


def is_sound(box: list[float]) -> bool:
    w, h = B.width_height(box)
    return w > 0 and h > 0


def _coords_evidence(ann: Annotation) -> dict:
    return {
        "box_xyxy": ann.bbox,
        "box_source": ann.bbox_source,
        "source_convention": "[x, y, width, height]"
        if ann.source_format.value == "coco_instances_json"
        else "[xtl, ytl, xbr, ybr]",
    }


@register
class ZeroAreaBox(Rule):
    id = "BOX001"
    name = "Zero-area box"
    group = "Bounding boxes"
    kind = IssueKind.STRUCTURAL
    severity = Severity.CRITICAL
    description = "Box width or height is exactly zero; it encloses no pixels."
    action = "Redraw the box around the object or delete it."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        for ann in _boxes(ctx):
            w, h = B.width_height(ann.bbox)
            if (w == 0 or h == 0) and w >= 0 and h >= 0:
                yield self.issue(
                    ctx,
                    annotation=ann,
                    title="Box has zero area",
                    description=f"Width {w:g} px × height {h:g} px.",
                    evidence={"width": w, "height": h, **_coords_evidence(ann)},
                )


@register
class NegativeBox(Rule):
    id = "BOX002"
    name = "Negative box dimensions"
    group = "Bounding boxes"
    kind = IssueKind.STRUCTURAL
    severity = Severity.CRITICAL
    description = "The far corner lies before the near corner (negative width or height)."
    action = "Swap the corner coordinates or redraw; many loaders reject this box."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        for ann in _boxes(ctx):
            w, h = B.width_height(ann.bbox)
            if w < 0 or h < 0:
                yield self.issue(
                    ctx,
                    annotation=ann,
                    title="Box has negative size",
                    description=f"Width {w:g} px, height {h:g} px.",
                    evidence={"width": w, "height": h, **_coords_evidence(ann)},
                )


@register
class OutOfBoundsBox(Rule):
    id = "BOX003"
    name = "Box outside image"
    group = "Bounding boxes"
    kind = IssueKind.STRUCTURAL
    severity = Severity.CRITICAL
    description = "Box coordinates extend past the image frame by more than the tolerance."
    action = "Clip the box to the image or correct the coordinates."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        tol = ctx.config.boxes.bounds_tolerance_px
        for ann in _boxes(ctx):
            size = ctx.image_size(ann)
            if size is None:
                continue
            w, h = size
            over = B.overshoot(ann.bbox, w, h)
            if over > tol:
                yield self.issue(
                    ctx,
                    annotation=ann,
                    title=f"Box exceeds the image by {over:.1f} px",
                    description=f"Image is {w:g} × {h:g}; box spans "
                    f"({ann.bbox[0]:g}, {ann.bbox[1]:g}) to ({ann.bbox[2]:g}, {ann.bbox[3]:g}).",
                    evidence={
                        "image_size": [w, h],
                        "overshoot_px": over,
                        "tolerance_px": tol,
                        "clipped_xyxy": B.clip(ann.bbox, w, h),
                        **_coords_evidence(ann),
                    },
                )


@register
class TinyBox(Rule):
    id = "BOX004"
    name = "Suspiciously small box"
    group = "Bounding boxes"
    kind = IssueKind.HEURISTIC
    severity = Severity.WARNING
    description = "Box area or shortest side is below the configured minimum; often a stray click."
    action = "Check whether this is a real distant object or an accidental box."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        t = ctx.config.boxes
        for ann in _boxes(ctx):
            if not is_sound(ann.bbox):
                continue
            w, h = B.width_height(ann.bbox)
            if w * h < t.min_area_px or min(w, h) < t.min_side_px:
                yield self.issue(
                    ctx,
                    annotation=ann,
                    title=f"Box is only {w:.0f} × {h:.0f} px",
                    description=f"Area {w * h:.0f} px² (minimum {t.min_area_px:g}); "
                    f"shortest side {min(w, h):.1f} px (minimum {t.min_side_px:g}).",
                    evidence={"width": w, "height": h, "area": w * h, **_coords_evidence(ann)},
                )


@register
class ExtremeAspectRatio(Rule):
    id = "BOX005"
    name = "Extreme aspect ratio"
    group = "Bounding boxes"
    kind = IssueKind.HEURISTIC
    severity = Severity.WARNING
    description = "Box is much longer than it is wide; typical of a drag that slipped."
    action = "Confirm the object really has this shape; otherwise redraw."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        limit = ctx.config.boxes.max_aspect_ratio
        for ann in _boxes(ctx):
            if not is_sound(ann.bbox):
                continue
            w, h = B.width_height(ann.bbox)
            ratio = max(w / h, h / w)
            if ratio > limit:
                yield self.issue(
                    ctx,
                    annotation=ann,
                    title=f"Aspect ratio {ratio:.1f} : 1",
                    description=f"{w:.0f} × {h:.0f} px exceeds the {limit:g} : 1 limit.",
                    evidence={"aspect_ratio": ratio, "limit": limit, **_coords_evidence(ann)},
                )


def _pairs_by_image(ctx: RuleContext) -> Iterator[tuple[Annotation, Annotation, float]]:
    groups: dict[str, list[Annotation]] = defaultdict(list)
    for ann in _boxes(ctx):
        if is_sound(ann.bbox):
            groups[ann.image_id].append(ann)
    for anns in groups.values():
        if len(anns) < 2:
            continue
        m = B.iou_matrix(np.array([a.bbox for a in anns], dtype=float))
        ii, jj = np.where(np.triu(m, k=1) > 0)
        for i, j in zip(ii.tolist(), jj.tolist(), strict=True):
            yield anns[i], anns[j], float(m[i, j])


@register
class NearDuplicateBox(Rule):
    id = "BOX006"
    name = "Near-duplicate box"
    group = "Bounding boxes"
    kind = IssueKind.HEURISTIC
    severity = Severity.WARNING
    description = "Two boxes with the same label overlap almost completely (IoU at or above threshold)."
    action = "Keep one box; duplicates inflate the class and confuse NMS-trained models."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        thr = ctx.config.boxes.duplicate_iou
        for a, b, iou in _pairs_by_image(ctx):
            if a.category == b.category and iou >= thr:
                yield self.issue(
                    ctx,
                    annotation=b,
                    title=f"Duplicates {a.id} (IoU {iou:.2f})",
                    description=f"Two '{b.category}' boxes overlap with IoU {iou:.3f} (threshold {thr:g}).",
                    evidence={
                        "other_annotation": a.id,
                        "iou": iou,
                        "threshold": thr,
                        "box_xyxy": b.bbox,
                        "other_xyxy": a.bbox,
                    },
                    key=a.id,
                )


@register
class ConflictingLabels(Rule):
    id = "BOX007"
    name = "Conflicting labels"
    group = "Bounding boxes"
    kind = IssueKind.HEURISTIC
    severity = Severity.WARNING
    description = "Boxes with different labels cover the same region; one label may be wrong."
    action = "Decide which label is correct and remove the other, or allow the pair in settings."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        t = ctx.config.boxes
        allowed = {frozenset(p) for p in t.allowed_overlap_pairs}
        for a, b, iou in _pairs_by_image(ctx):
            if a.category == b.category or iou < t.conflict_iou:
                continue
            if frozenset((a.category, b.category)) in allowed:
                continue
            yield self.issue(
                ctx,
                annotation=b,
                title=f"'{b.category}' overlaps '{a.category}' (IoU {iou:.2f})",
                description=f"Annotation {b.id} ('{b.category}') and {a.id} ('{a.category}') "
                f"cover the same region with IoU {iou:.3f}.",
                evidence={
                    "other_annotation": a.id,
                    "other_label": a.category,
                    "iou": iou,
                    "threshold": t.conflict_iou,
                    "box_xyxy": b.bbox,
                    "other_xyxy": a.bbox,
                },
                key=a.id,
            )
