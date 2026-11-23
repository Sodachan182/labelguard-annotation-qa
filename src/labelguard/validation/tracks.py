"""Video-track rules (TRK) following CVAT for video semantics.

* Shapes are sorted by frame within a track.
* ``outside="1"`` means the object left the frame from that frame on; its
  coordinates are stale and ignored. A visible shape after an outside shape
  starts a new segment and must be a keyframe.
* Frames between two keyframes are interpolated by CVAT. A gap is therefore
  *not* a missing annotation unless the explicit gap policy is selected.
"""

from __future__ import annotations

import itertools
import math
from collections import defaultdict
from collections.abc import Iterator

from labelguard.geometry import boxes as B
from labelguard.models import Annotation, IssueKind, QualityIssue, Severity
from labelguard.validation.engine import Rule, RuleContext, register


def _tracks(ctx: RuleContext) -> dict[str, list[Annotation]]:
    out: dict[str, list[Annotation]] = defaultdict(list)
    for ann in ctx.dataset.annotations:
        if ann.track_id is not None:
            out[ann.track_id].append(ann)
    for shapes in out.values():
        shapes.sort(key=lambda a: a.frame if a.frame is not None else -1)
    return out


def _box(ann: Annotation) -> list[float] | None:
    if ann.bbox is not None and B.is_finite(ann.bbox):
        w, h = B.width_height(ann.bbox)
        return ann.bbox if w > 0 and h > 0 else None
    ext = ann.extent()
    if ext and ext[2] > ext[0] and ext[3] > ext[1]:
        return list(ext)
    return None


def _visible_steps(shapes: list[Annotation]) -> Iterator[tuple[Annotation, Annotation, int]]:
    """Consecutive pairs inside one visible segment (no outside shape between)."""
    for prev, cur in itertools.pairwise(shapes):
        if prev.outside or cur.outside or prev.frame is None or cur.frame is None:
            continue
        delta = cur.frame - prev.frame
        if delta > 0:
            yield prev, cur, delta


@register
class InvalidFrameReference(Rule):
    id = "TRK001"
    name = "Invalid frame reference"
    group = "Tracking"
    kind = IssueKind.STRUCTURAL
    severity = Severity.CRITICAL
    description = "A track shape references a frame outside the task range, or repeats a frame."
    action = "Move the shape to a valid frame or delete the duplicate."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        ds = ctx.dataset
        if not ds.is_video:
            return
        start, stop = ds.frame_range or (0, math.inf)
        for track_id, shapes in _tracks(ctx).items():
            seen: dict[int, str] = {}
            for ann in shapes:
                f = ann.frame if ann.frame is not None else -1
                if f < start or f > stop:
                    yield self.issue(
                        ctx,
                        annotation=ann,
                        title=f"Frame {f} is outside the video",
                        description=f"Track {track_id} has a shape on frame {f}; the task spans frames {start}–{stop}.",
                        evidence={"frame": f, "frame_range": [start, stop]},
                    )
                elif f in seen:
                    yield self.issue(
                        ctx,
                        annotation=ann,
                        title=f"Frame {f} appears twice in track {track_id}",
                        description=f"Shapes {seen[f]} and {ann.id} both claim frame {f}.",
                        evidence={"frame": f, "other_annotation": seen[f]},
                        key="dup",
                    )
                else:
                    seen[f] = ann.id


@register
class TrackMetadataConflict(Rule):
    id = "TRK002"
    name = "Track metadata conflict"
    group = "Tracking"
    kind = IssueKind.STRUCTURAL
    severity = Severity.WARNING
    description = "A track has no shapes, is never visible, or mixes geometry types."
    action = "Delete the empty track or fix its shapes."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        ds = ctx.dataset
        if not ds.is_video:
            return
        tracks = _tracks(ctx)
        for tr in ds.tracks:
            shapes = tracks.get(tr.id, [])
            problem = None
            if not shapes:
                problem = "Track has no shapes."
            elif all(s.outside for s in shapes):
                problem = "Every shape in the track is marked outside; it is never visible."
            elif len({s.geometry_type for s in shapes}) > 1:
                kinds = sorted({s.geometry_type.value for s in shapes})
                problem = f"Track mixes geometry types: {', '.join(kinds)}."
            if problem:
                yield self.issue(
                    ctx,
                    annotation=shapes[0] if shapes else None,
                    title=f"Track {tr.id} ({tr.label}) is inconsistent",
                    description=problem,
                    evidence={"track": tr.id, "label": tr.label, "shapes": len(shapes)},
                    track_id=tr.id,
                    source_location=tr.source_location,
                    key=f"track:{tr.id}",
                )


@register
class VisibilityTransition(Rule):
    id = "TRK003"
    name = "Invalid visibility transition"
    group = "Tracking"
    kind = IssueKind.STRUCTURAL
    severity = Severity.WARNING
    description = (
        "After an 'outside' shape the object must re-enter on a keyframe; "
        "a non-keyframe visible shape there cannot be produced by interpolation."
    )
    action = "Mark the re-entry shape as a keyframe or correct the outside flag."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        if not ctx.dataset.is_video:
            return
        for track_id, shapes in _tracks(ctx).items():
            for prev, cur in itertools.pairwise(shapes):
                if prev.outside and not cur.outside and cur.keyframe is False:
                    yield self.issue(
                        ctx,
                        annotation=cur,
                        title=f"Re-entry on frame {cur.frame} is not a keyframe",
                        description=f"Track {track_id} is outside on frame {prev.frame} and "
                        f"visible again on frame {cur.frame} without a keyframe.",
                        evidence={"previous_frame": prev.frame, "frame": cur.frame, "keyframe": cur.keyframe},
                    )


@register
class MovementJump(Rule):
    id = "TRK004"
    name = "Suspicious movement jump"
    group = "Tracking"
    kind = IssueKind.HEURISTIC
    severity = Severity.WARNING
    description = (
        "The object's centre moves further per frame than a multiple of its own size; "
        "often an identity switch or a mis-placed keyframe."
    )
    action = "Scrub the frames around this shape and check the track identity."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        if not ctx.dataset.is_video:
            return
        limit = ctx.config.tracks.max_jump_ratio
        for track_id, shapes in _tracks(ctx).items():
            for prev, cur, delta in _visible_steps(shapes):
                a, b = _box(prev), _box(cur)
                if a is None or b is None:
                    continue
                (ax, ay), (bx, by) = B.center(a), B.center(b)
                disp = math.hypot(bx - ax, by - ay)
                ratio = disp / delta / max(B.diagonal(a), 1.0)
                if ratio > limit:
                    yield self.issue(
                        ctx,
                        annotation=cur,
                        title=f"Jumps {disp:.0f} px between frames {prev.frame} and {cur.frame}",
                        description=f"Centre moves {ratio:.2f}× the box diagonal per frame (limit {limit:g}).",
                        evidence={
                            "track": track_id,
                            "from_frame": prev.frame,
                            "to_frame": cur.frame,
                            "displacement_px": disp,
                            "ratio_per_frame": ratio,
                            "limit": limit,
                        },
                    )


@register
class ScaleChange(Rule):
    id = "TRK005"
    name = "Sudden scale change"
    group = "Tracking"
    kind = IssueKind.HEURISTIC
    severity = Severity.WARNING
    description = "Box area changes by more than the configured factor per frame."
    action = "Check whether the box was resized by mistake on this frame."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        if not ctx.dataset.is_video:
            return
        limit = ctx.config.tracks.max_scale_change
        for track_id, shapes in _tracks(ctx).items():
            for prev, cur, delta in _visible_steps(shapes):
                a, b = _box(prev), _box(cur)
                if a is None or b is None:
                    continue
                r = max(B.area(b) / B.area(a), B.area(a) / B.area(b))
                per_frame = r ** (1.0 / delta)
                if per_frame > limit:
                    yield self.issue(
                        ctx,
                        annotation=cur,
                        title=f"Area changes {r:.1f}× between frames {prev.frame} and {cur.frame}",
                        description=f"{per_frame:.2f}× per frame exceeds the {limit:g}× limit.",
                        evidence={
                            "track": track_id,
                            "area_before": B.area(a),
                            "area_after": B.area(b),
                            "ratio_per_frame": per_frame,
                            "limit": limit,
                        },
                    )


@register
class ContinuityGap(Rule):
    id = "TRK006"
    name = "Track continuity gap"
    group = "Tracking"
    kind = IssueKind.HEURISTIC
    severity = Severity.INFO
    description = (
        "Only with the 'explicit' gap policy: a visible track has no shape for more "
        "than the allowed number of frames. Under CVAT's default interpolation this is normal."
    )
    action = "Confirm the object is really continuously visible, or add an outside marker."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        t = ctx.config.tracks
        if not ctx.dataset.is_video or t.gap_policy != "explicit":
            return
        for track_id, shapes in _tracks(ctx).items():
            for prev, cur, delta in _visible_steps(shapes):
                if delta > t.max_gap:
                    yield self.issue(
                        ctx,
                        annotation=cur,
                        title=f"{delta - 1} frames without a shape",
                        description=f"Track {track_id} jumps from frame {prev.frame} to {cur.frame}.",
                        evidence={"from_frame": prev.frame, "to_frame": cur.frame, "max_gap": t.max_gap},
                    )
