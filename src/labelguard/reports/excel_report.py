"""Formatted XLSX report: Summary, Issues, Categories, Rules, Configuration."""

from __future__ import annotations

import io
import json

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from labelguard.analytics.statistics import category_counts, rule_counts
from labelguard.models import Dataset, QualityReport
from labelguard.reports.exporters import CSV_COLUMNS, report_summary, safe_cell

HEADER_FILL = PatternFill("solid", fgColor="1D2229")
HEADER_FONT = Font(bold=True, color="FFFFFF")
SEVERITY_FONT = {
    "critical": Font(color="B93A3A", bold=True),
    "warning": Font(color="9A6A12", bold=True),
    "info": Font(color="2F6DB0"),
}
THIN = Border(bottom=Side(style="thin", color="DEDAD2"))


def _table(ws: Worksheet, headers: list[str], rows: list[list], widths: dict[int, int] | None = None):
    ws.append(headers)
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(vertical="center")
    for row in rows:
        ws.append([safe_cell(v) for v in row])
    ws.freeze_panes = "A2"
    if rows:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(rows) + 1}"
    for idx, h in enumerate(headers, start=1):
        width = (widths or {}).get(idx) or min(
            60, max(len(str(h)), *(len(str(r[idx - 1])) for r in rows[:200])) + 2 if rows else len(h) + 2
        )
        ws.column_dimensions[get_column_letter(idx)].width = width


def to_xlsx(report: QualityReport, dataset: Dataset | None = None) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    summary = report_summary(report)
    ws.append(["LabelGuard quality report"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([])
    for key, value in summary.items():
        if isinstance(value, dict):
            for k, v in value.items():
                ws.append([safe_cell(f"{key.replace('_', ' ')}: {k}"), v])
        else:
            ws.append([key.replace("_", " ").capitalize(), safe_cell(value)])
    ws.append([])
    ws.append(
        [
            "Quality score is an application-specific heuristic: 100 × (1 − Σ penalty / annotations), "
            "penalty 1.0 for critical, 0.4 for warning."
        ]
    )
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 44

    issues = wb.create_sheet("Issues")
    rows = []
    for i in report.issues:
        d = i.model_dump(mode="json")
        d["evidence"] = json.dumps(d["evidence"], ensure_ascii=False)[:2000]
        rows.append([d.get(c) for c in CSV_COLUMNS])
    _table(issues, CSV_COLUMNS, rows, widths={14: 40, 15: 60, 16: 50, 18: 50})
    for r_idx, issue in enumerate(report.issues, start=2):
        issues.cell(row=r_idx, column=2).font = SEVERITY_FONT[issue.severity.value]
        for c in range(1, len(CSV_COLUMNS) + 1):
            issues.cell(row=r_idx, column=c).border = THIN

    cats = wb.create_sheet("Categories")
    if dataset is not None:
        cdf = category_counts(dataset)
        flagged: dict[str, int] = {}
        for i in report.issues:
            if i.category:
                flagged[i.category] = flagged.get(i.category, 0) + 1
        _table(
            cats,
            ["Category", "Annotations", "Findings"],
            [[r.category, int(r.annotations), flagged.get(r.category, 0)] for r in cdf.itertuples()],
        )
    else:
        cats.append(["Category statistics need the parsed dataset."])

    rules = wb.create_sheet("Rules")
    rdf = rule_counts(report)
    _table(
        rules,
        ["Rule", "Name", "Kind", "Severity", "Findings"],
        [[r.rule_id, r.rule_name, r.kind, r.severity, int(r.findings)] for r in rdf.itertuples()],
    )

    cfg = wb.create_sheet("Configuration")
    flat: list[list] = []

    def walk(prefix: str, obj) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(f"{prefix}.{k}" if prefix else k, v)
        else:
            flat.append([prefix, json.dumps(obj) if isinstance(obj, (list, tuple)) else obj])

    walk("", report.config)
    _table(cfg, ["Setting", "Value"], flat, widths={1: 40, 2: 50})

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
