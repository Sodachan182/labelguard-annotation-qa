"""CSV and JSON report export.

Spreadsheet formula injection: any text cell starting with ``= + - @`` or a
tab / carriage return is prefixed with an apostrophe in CSV and XLSX so a
spreadsheet application treats it as text. Annotation labels and file names
come from untrusted datasets, so this matters.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from labelguard import __version__
from labelguard.analytics.statistics import quality_score, rule_counts, severity_counts
from labelguard.models import QualityReport

_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")

CSV_COLUMNS = [
    "issue_id",
    "severity",
    "kind",
    "rule_id",
    "rule_name",
    "dataset_id",
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
    "evidence",
]


def safe_cell(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(_DANGEROUS):
        return "'" + value
    return value


def report_summary(report: QualityReport) -> dict[str, Any]:
    score = quality_score(report)
    return {
        "dataset": report.dataset_name,
        "dataset_id": report.dataset_id,
        "format": report.source_format.label,
        "profile": report.profile,
        "generated_at": report.generated_at.isoformat(timespec="seconds"),
        "labelguard_version": __version__,
        "images": report.image_count,
        "annotations": report.annotation_count,
        "findings": len(report.issues),
        "by_severity": severity_counts(report),
        "structural_findings": sum(1 for i in report.issues if i.kind.value == "structural"),
        "heuristic_findings": sum(1 for i in report.issues if i.kind.value == "heuristic"),
        "quality_score": round(score, 1) if score is not None else None,
        "rules_run": len(report.rules_run),
        "duration_ms": round(report.duration_ms, 1),
    }


def to_json(report: QualityReport) -> str:
    payload = {
        "summary": report_summary(report),
        "rules": rule_counts(report).to_dict(orient="records"),
        "config": report.config,
        "issues": [i.model_dump(mode="json") for i in report.issues],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def to_csv(report: QualityReport) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for issue in report.issues:
        row = issue.model_dump(mode="json")
        row["evidence"] = json.dumps(row["evidence"], ensure_ascii=False)
        writer.writerow({k: safe_cell(row.get(k)) for k in CSV_COLUMNS})
    return buf.getvalue()
