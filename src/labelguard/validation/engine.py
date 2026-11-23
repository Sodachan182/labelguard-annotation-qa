"""Rule registry and validation engine.

A rule is a small class with a stable id, a default severity, a kind
(structural or heuristic) and a ``check`` generator. Rules never mutate the
dataset; the engine collects their findings into a :class:`QualityReport`.
"""

from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, ClassVar

from labelguard.config import ValidationConfig
from labelguard.models import (
    Annotation,
    Dataset,
    ImageRecord,
    IssueKind,
    QualityIssue,
    QualityReport,
    Severity,
)


@dataclass
class RuleContext:
    dataset: Dataset
    config: ValidationConfig
    images: dict[str, ImageRecord] = field(init=False)

    def __post_init__(self) -> None:
        self.images = {}
        for img in self.dataset.images:
            self.images.setdefault(img.id, img)
            src = str(img.raw.get("source_id", img.id))
            self.images.setdefault(src, img)

    def image_for(self, ann: Annotation) -> ImageRecord | None:
        return self.images.get(ann.image_id)

    def image_size(self, ann: Annotation) -> tuple[float, float] | None:
        img = self.image_for(ann)
        if img is None or not img.has_valid_size:
            return None
        return float(img.width), float(img.height)  # type: ignore[arg-type]


class Rule:
    id: ClassVar[str]
    name: ClassVar[str]
    group: ClassVar[str]
    kind: ClassVar[IssueKind]
    severity: ClassVar[Severity]
    description: ClassVar[str]
    action: ClassVar[str] = ""
    profiles: ClassVar[set[str] | None] = None  # None = every profile

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:  # pragma: no cover
        raise NotImplementedError

    # ------------------------------------------------------------------ helpers
    def issue(
        self,
        ctx: RuleContext,
        *,
        title: str,
        description: str,
        annotation: Annotation | None = None,
        image: ImageRecord | None = None,
        evidence: dict[str, Any] | None = None,
        action: str | None = None,
        severity: Severity | None = None,
        key: str = "",
        track_id: str | None = None,
        source_location: str | None = None,
    ) -> QualityIssue:
        ds = ctx.dataset
        if image is None and annotation is not None:
            image = ctx.image_for(annotation)
        image_id = image.id if image else (annotation.image_id if annotation else None)
        frame = annotation.frame if annotation else (image.frame if image else None)
        ident = "|".join(str(x) for x in (ds.id, self.id, image_id, annotation.id if annotation else "", key))
        digest = hashlib.sha1(ident.encode(), usedforsecurity=False).hexdigest()[:8].upper()
        return QualityIssue(
            issue_id=f"LG-{digest}",
            rule_id=self.id,
            rule_name=self.name,
            severity=severity or self.severity,
            kind=self.kind,
            dataset_id=ds.id,
            image_id=image_id,
            image_name=image.file_name if image else None,
            frame_id=frame,
            annotation_id=annotation.id if annotation else None,
            track_id=track_id or (annotation.track_id if annotation else None),
            category=annotation.category if annotation else None,
            geometry_type=annotation.geometry_type.value if annotation else None,
            title=title,
            description=description,
            evidence=_clean(evidence or {}),
            suggested_action=action if action is not None else self.action,
            source_location=source_location
            or (annotation.source_location if annotation else (image.source_location if image else "")),
        )


def _clean(value: Any) -> Any:
    """Make evidence JSON-safe (NaN/inf -> strings, tuples -> lists, round floats)."""
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        return round(value, 3)
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


RULES: dict[str, type[Rule]] = {}


def register(cls: type[Rule]) -> type[Rule]:
    if cls.id in RULES:
        raise ValueError(f"Duplicate rule id {cls.id}")
    RULES[cls.id] = cls
    return cls


def _load_rule_modules() -> None:
    # Importing registers the rules.
    from labelguard.validation import (  # noqa: F401
        bounding_boxes,
        integrity,
        keypoints,
        polygons,
        tracks,
    )


def all_rules() -> list[type[Rule]]:
    _load_rule_modules()
    return [RULES[k] for k in sorted(RULES)]


def active_rules(config: ValidationConfig) -> list[type[Rule]]:
    out = []
    for rule in all_rules():
        if config.enabled_rules is not None and rule.id not in config.enabled_rules:
            continue
        if rule.id in config.disabled_rules:
            continue
        if rule.profiles is not None and config.profile not in rule.profiles:
            continue
        out.append(rule)
    return out


def validate(
    dataset: Dataset,
    config: ValidationConfig | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> QualityReport:
    config = config or ValidationConfig()
    ctx = RuleContext(dataset=dataset, config=config)
    rules = active_rules(config)
    issues: list[QualityIssue] = []
    seen: set[str] = set()
    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    for i, rule_cls in enumerate(rules):
        if progress:
            progress(i / max(len(rules), 1), f"{rule_cls.id} {rule_cls.name}")
        t_rule = time.perf_counter()
        for issue in rule_cls().check(ctx):
            if issue.issue_id in seen:
                continue
            seen.add(issue.issue_id)
            override = config.severity_overrides.get(issue.rule_id)
            if override:
                issue.severity = override
            issues.append(issue)
        timings[rule_cls.id] = (time.perf_counter() - t_rule) * 1000
    if progress:
        progress(1.0, "Done")
    issues.sort(
        key=lambda x: (
            x.severity.rank,
            x.rule_id,
            x.frame_id if x.frame_id is not None else -1,
            x.image_id or "",
            x.annotation_id or "",
        )
    )
    return QualityReport(
        dataset_id=dataset.id,
        dataset_name=dataset.name,
        source_format=dataset.source_format,
        profile=config.profile,
        config=config.model_dump(mode="json"),
        image_count=len(dataset.images),
        annotation_count=len(dataset.annotations),
        issues=issues,
        rules_run=[r.id for r in rules],
        duration_ms=(time.perf_counter() - t0) * 1000,
        rule_timings_ms=timings,
    )


# ------------------------------------------------------------ shared helpers


def classify_parse_error(message: str) -> str:
    """'missing' | 'structure' | 'value' — routes parse errors to one rule each."""
    m = message.lower()
    if m.startswith("missing"):
        return "missing"
    if any(k in m for k in ("malformed", "odd number", "multiple of 3", "is not a list", "must be [")):
        return "structure"
    return "value"


def finite(values: Iterable[float]) -> bool:
    return all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)
