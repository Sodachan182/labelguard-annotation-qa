"""Validation configuration and rule profiles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from labelguard.models import Severity


class BoxThresholds(BaseModel):
    bounds_tolerance_px: float = Field(1.0, ge=0, description="Allowed overshoot past the image edge.")
    min_area_px: float = Field(36.0, ge=0, description="Boxes smaller than this are 'tiny'.")
    min_side_px: float = Field(4.0, ge=0)
    max_aspect_ratio: float = Field(12.0, gt=1)
    duplicate_iou: float = Field(0.9, gt=0, le=1, description="Same label, IoU at or above.")
    conflict_iou: float = Field(0.85, gt=0, le=1, description="Different labels, IoU at or above.")
    allowed_overlap_pairs: list[tuple[str, str]] = Field(default_factory=list)


class PolygonThresholds(BaseModel):
    bounds_tolerance_px: float = Field(1.0, ge=0)
    min_area_px: float = Field(36.0, ge=0)


class KeypointThresholds(BaseModel):
    bounds_tolerance_px: float = Field(1.0, ge=0)
    expected_count: int | None = Field(None, ge=1, description="Overrides the category schema when set.")
    bbox_margin_ratio: float = Field(0.25, ge=0, description="Keypoints further than this fraction outside their box.")
    # Pairs (a, b) asserting x(a) < x(b) in image space, e.g. a mirrored-label check.
    order_rules: list[tuple[str, str]] = Field(default_factory=list)


class TrackThresholds(BaseModel):
    max_jump_ratio: float = Field(0.6, gt=0, description="Center displacement per frame / box diagonal.")
    max_scale_change: float = Field(1.6, gt=1, description="Area ratio per frame.")
    gap_policy: Literal["interpolated", "explicit"] = Field(
        "interpolated",
        description=(
            "'interpolated' follows CVAT semantics: gaps between keyframes are "
            "interpolated and never flagged. 'explicit' flags gaps longer than max_gap."
        ),
    )
    max_gap: int = Field(10, ge=1)


class ValidationConfig(BaseModel):
    profile: str = "general_detection"
    enabled_rules: list[str] | None = Field(None, description="None means every rule in the profile is enabled.")
    disabled_rules: list[str] = Field(default_factory=list)
    severity_overrides: dict[str, Severity] = Field(default_factory=dict)
    boxes: BoxThresholds = Field(default_factory=BoxThresholds)
    polygons: PolygonThresholds = Field(default_factory=PolygonThresholds)
    keypoints: KeypointThresholds = Field(default_factory=KeypointThresholds)
    tracks: TrackThresholds = Field(default_factory=TrackThresholds)
    # Allowed attribute values per label, in addition to any CVAT schema.
    attribute_schema: dict[str, dict[str, list[str]]] = Field(default_factory=dict)

    @field_validator("profile")
    @classmethod
    def _known_profile(cls, v: str) -> str:
        if v not in PROFILES:
            raise ValueError(f"Unknown profile '{v}'. Choose one of: {', '.join(PROFILES)}")
        return v

    @classmethod
    def from_file(cls, path: str | Path) -> ValidationConfig:
        return cls.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def for_profile(cls, profile: str) -> ValidationConfig:
        return PROFILES[profile].build()


class Profile(BaseModel):
    id: str
    name: str
    description: str
    disabled_rules: list[str] = Field(default_factory=list)
    overrides: dict = Field(default_factory=dict)

    def build(self) -> ValidationConfig:
        data = {"profile": self.id, "disabled_rules": list(self.disabled_rules)}
        data.update(self.overrides)
        return ValidationConfig.model_validate(data)


PROFILES: dict[str, Profile] = {
    p.id: p
    for p in [
        Profile(
            id="general_detection",
            name="General object detection",
            description="Every structural rule plus box heuristics. Sensible default.",
        ),
        Profile(
            id="instance_segmentation",
            name="Instance segmentation",
            description="Stricter polygon checks; box aspect-ratio heuristic relaxed.",
            overrides={
                "polygons": {"min_area_px": 64.0},
                "boxes": {"max_aspect_ratio": 20.0},
            },
        ),
        Profile(
            id="video_tracking",
            name="Video tracking",
            description="Track continuity, motion and visibility checks with CVAT semantics.",
            overrides={"boxes": {"min_area_px": 16.0}},
        ),
        Profile(
            id="face_landmarks",
            name="Face landmarks",
            description=(
                "Keypoint schema, bounds and left/right ordering for frontal faces. "
                "Ordering assumes a camera-facing subject and is a heuristic."
            ),
            overrides={
                "keypoints": {"order_rules": [["right_eye", "left_eye"], ["mouth_right", "mouth_left"]]},
                "boxes": {"min_area_px": 100.0},
            },
        ),
        Profile(
            id="bdd100k_detection",
            name="BDD100K driving detection",
            description=(
                "General detection rules for dash-cam data. Riders legitimately overlap "
                "their bike or motorcycle, so those pairs never produce conflict findings."
            ),
            overrides={
                "boxes": {
                    "allowed_overlap_pairs": [
                        ["rider", "bike"],
                        ["rider", "motor"],
                        ["rider", "bicycle"],
                        ["rider", "motorcycle"],
                    ]
                }
            },
        ),
        Profile(
            id="seat_belt",
            name="Seat belt annotation",
            description=(
                "In-cabin profile: allows 'seat_belt' to overlap 'person'/'occupant' "
                "without conflict findings and relaxes the aspect heuristic for thin "
                "belt boxes. It does not recognise whether a belt is worn."
            ),
            overrides={
                "boxes": {
                    "max_aspect_ratio": 25.0,
                    "allowed_overlap_pairs": [
                        ["seat_belt", "person"],
                        ["seat_belt", "occupant"],
                    ],
                }
            },
        ),
    ]
}
