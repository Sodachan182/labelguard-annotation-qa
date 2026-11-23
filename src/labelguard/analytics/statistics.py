"""Dataset statistics and the LabelGuard quality score.

Quality score (application-specific heuristic, 0–100):

    penalty(a) = 1.0 if annotation a has any critical finding
               = 0.4 if its worst finding is a warning
               = 0   otherwise (info or no finding)
    score      = 100 × (1 − Σ penalty / annotation_count)

Dataset-level findings (no annotation id) do not affect the score. The score is
a triage aid for comparing runs on the same dataset, not a measure of label
correctness.
"""

from __future__ import annotations

import math
from collections import Counter

import pandas as pd

from labelguard.geometry import boxes as B
from labelguard.models import Dataset, QualityReport, Severity

SCORE_WEIGHTS = {Severity.CRITICAL: 1.0, Severity.WARNING: 0.4, Severity.INFO: 0.0}


def quality_score(report: QualityReport) -> float | None:
    if report.annotation_count == 0:
        return None
    worst: dict[str, Severity] = {}
    for issue in report.issues:
        if not issue.annotation_id:
            continue
        cur = worst.get(issue.annotation_id)
        if cur is None or issue.severity.rank < cur.rank:
            worst[issue.annotation_id] = issue.severity
    penalty = sum(SCORE_WEIGHTS[s] for s in worst.values())
    return max(0.0, 100.0 * (1.0 - penalty / report.annotation_count))


def category_counts(ds: Dataset) -> pd.DataFrame:
    counts = Counter(a.category or "(none)" for a in ds.annotations)
    df = pd.DataFrame(counts.items(), columns=["category", "annotations"])
    return df.sort_values(["annotations", "category"], ascending=[False, True]).reset_index(drop=True)


def geometry_counts(ds: Dataset) -> dict[str, int]:
    return dict(Counter(a.geometry_type.value for a in ds.annotations))


def issues_frame(report: QualityReport) -> pd.DataFrame:
    cols = [
        "issue_id",
        "severity",
        "kind",
        "rule_id",
        "rule_name",
        "image_id",
        "image_name",
        "frame_id",
        "annotation_id",
        "track_id",
        "category",
        "geometry_type",
        "title",
        "description",
        "suggested_action",
        "source_location",
    ]
    if not report.issues:
        return pd.DataFrame(columns=cols)
    rows = [i.model_dump(mode="json", include=set(cols)) for i in report.issues]
    return pd.DataFrame(rows)[cols]


def severity_counts(report: QualityReport) -> dict[str, int]:
    return {s.label: report.count(s) for s in Severity}


def rule_counts(report: QualityReport) -> pd.DataFrame:
    c = Counter((i.rule_id, i.rule_name, i.kind.value, i.severity.value) for i in report.issues)
    df = pd.DataFrame(
        [(r, n, k, s, v) for (r, n, k, s), v in c.items()],
        columns=["rule_id", "rule_name", "kind", "severity", "findings"],
    )
    return df.sort_values(["findings", "rule_id"], ascending=[False, True]).reset_index(drop=True)


def box_sizes(ds: Dataset) -> pd.DataFrame:
    """Relative box size sqrt(box area / image area) for every sound box."""
    images = ds.image_by_id()
    rows = []
    for a in ds.annotations:
        box = a.bbox
        if box is None and a.polygons:
            ext = a.extent()
            box = list(ext) if ext else None
        if box is None or not B.is_finite(box) or a.outside:
            continue
        img = images.get(a.image_id)
        ar = B.area(box)
        if ar <= 0:
            continue
        rel = None
        if img is not None and img.has_valid_size:
            rel = math.sqrt(ar / (img.width * img.height))  # type: ignore[operator]
        rows.append({"category": a.category or "(none)", "area_px": ar, "relative_size": rel})
    return pd.DataFrame(rows, columns=["category", "area_px", "relative_size"])


def per_image_issue_counts(report: QualityReport) -> Counter:
    return Counter(i.image_id for i in report.issues if i.image_id)
