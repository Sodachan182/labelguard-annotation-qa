"""Normalized, format-independent data model.

Parsers translate CVAT / COCO into these structures; validators only ever see
these structures. Original coordinates are preserved in ``bbox_source`` and
``raw`` so reports can quote the source format exactly.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class GeometryType(StrEnum):
    BBOX = "bbox"
    POLYGON = "polygon"
    POLYLINE = "polyline"
    POINTS = "points"
    KEYPOINTS = "keypoints"
    UNSUPPORTED = "unsupported"


class Severity(StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"

    @property
    def rank(self) -> int:
        return {"critical": 0, "warning": 1, "info": 2}[self.value]

    @property
    def label(self) -> str:
        return self.value.capitalize()


class IssueKind(StrEnum):
    """Structural = the data violates the format or geometry definition.
    Heuristic = the data is valid but statistically or geometrically suspicious."""

    STRUCTURAL = "structural"
    HEURISTIC = "heuristic"


class SourceFormat(StrEnum):
    CVAT_IMAGES = "cvat_images_xml"
    CVAT_VIDEO = "cvat_video_xml"
    COCO = "coco_instances_json"
    BDD100K = "bdd100k_json"

    @property
    def label(self) -> str:
        return {
            "cvat_images_xml": "CVAT for images (XML)",
            "cvat_video_xml": "CVAT for video (XML)",
            "coco_instances_json": "COCO instances (JSON)",
            "bdd100k_json": "BDD100K / Scalabel (JSON)",
        }[self.value]


class AttributeSpec(BaseModel):
    name: str
    input_type: str = "text"
    values: list[str] = Field(default_factory=list)
    mutable: bool = False


class Category(BaseModel):
    id: str
    name: str
    keypoint_names: list[str] = Field(default_factory=list)
    attributes: list[AttributeSpec] = Field(default_factory=list)


class ImageRecord(BaseModel):
    id: str
    file_name: str
    width: float | None = None
    height: float | None = None
    frame: int | None = None
    source_location: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def has_valid_size(self) -> bool:
        return (
            self.width is not None
            and self.height is not None
            and math.isfinite(self.width)
            and math.isfinite(self.height)
            and self.width > 0
            and self.height > 0
        )


class Annotation(BaseModel):
    id: str
    image_id: str
    category: str = ""
    category_id: str | None = None
    geometry_type: GeometryType
    frame: int | None = None
    track_id: str | None = None
    # Normalized corner box [x1, y1, x2, y2] — only when the source declares a box.
    bbox: list[float] | None = None
    # Box exactly as written in the source (COCO: [x, y, w, h]; CVAT: [xtl, ytl, xbr, ybr]).
    bbox_source: list[float] | None = None
    polygons: list[list[list[float]]] = Field(default_factory=list)
    points: list[list[float]] = Field(default_factory=list)
    keypoint_visibility: list[int] = Field(default_factory=list)
    attributes: dict[str, str] = Field(default_factory=dict)
    occluded: bool = False
    outside: bool = False
    keyframe: bool | None = None
    source_format: SourceFormat
    source_location: str = ""
    parse_errors: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)

    def all_xy(self) -> list[list[float]]:
        """Every coordinate pair this annotation declares."""
        pts: list[list[float]] = []
        if self.bbox is not None:
            pts += [[self.bbox[0], self.bbox[1]], [self.bbox[2], self.bbox[3]]]
        for ring in self.polygons:
            pts += ring
        pts += self.points
        return pts

    def extent(self) -> tuple[float, float, float, float] | None:
        """Finite bounding extent of all coordinates, or None."""
        pts = [p for p in self.all_xy() if len(p) >= 2 and all(map(math.isfinite, p[:2]))]
        if not pts:
            return None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)


class Track(BaseModel):
    id: str
    label: str
    source: str = ""
    attributes: dict[str, str] = Field(default_factory=dict)
    source_location: str = ""


class Dataset(BaseModel):
    id: str
    name: str
    source_format: SourceFormat
    images: list[ImageRecord] = Field(default_factory=list)
    annotations: list[Annotation] = Field(default_factory=list)
    categories: list[Category] = Field(default_factory=list)
    tracks: list[Track] = Field(default_factory=list)
    frame_range: tuple[int, int] | None = None
    parse_warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Map of image record id -> absolute path of the pixel file, when supplied.
    image_paths: dict[str, str] = Field(default_factory=dict)

    @property
    def is_video(self) -> bool:
        return self.source_format == SourceFormat.CVAT_VIDEO

    def image_by_id(self) -> dict[str, ImageRecord]:
        return {img.id: img for img in self.images}

    def category_names(self) -> set[str]:
        return {c.name for c in self.categories}


class QualityIssue(BaseModel):
    issue_id: str
    rule_id: str
    rule_name: str
    severity: Severity
    kind: IssueKind
    dataset_id: str
    image_id: str | None = None
    image_name: str | None = None
    frame_id: int | None = None
    annotation_id: str | None = None
    track_id: str | None = None
    category: str | None = None
    geometry_type: str | None = None
    title: str
    description: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    suggested_action: str = ""
    source_location: str = ""


class RuleStat(BaseModel):
    rule_id: str
    rule_name: str
    kind: IssueKind
    severity: Severity
    count: int


class QualityReport(BaseModel):
    dataset_id: str
    dataset_name: str
    source_format: SourceFormat
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    profile: str
    config: dict[str, Any]
    image_count: int
    annotation_count: int
    issues: list[QualityIssue]
    rules_run: list[str]
    duration_ms: float = 0.0
    rule_timings_ms: dict[str, float] = Field(default_factory=dict)

    def count(self, severity: Severity) -> int:
        return sum(1 for i in self.issues if i.severity == severity)

    @property
    def flagged_annotation_ids(self) -> set[str]:
        return {i.annotation_id for i in self.issues if i.annotation_id}
