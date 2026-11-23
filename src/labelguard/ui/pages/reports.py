"""Screen E — Reports."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from labelguard.analytics.statistics import quality_score, rule_counts
from labelguard.models import Severity
from labelguard.reports import report_summary, to_csv, to_json, to_xlsx
from labelguard.ui import state
from labelguard.ui.common import context_line, ensure_report, require_dataset
from labelguard.ui.styles import divider, dl, page_header, section


@st.cache_data(show_spinner=False, max_entries=8)
def _xlsx(entry_id: str, generated_at: str) -> bytes:
    e = state.entries()[entry_id]
    return to_xlsx(e.report, e.dataset)


def render() -> None:
    entry = state.active()
    page_header("Reports", "Export the findings of the last validation run.", context_line(entry) if entry else None)
    divider()
    entry = require_dataset()
    if entry is None:
        return
    report = ensure_report(entry)
    summary = report_summary(report)
    stem = Path(entry.dataset.name).stem.replace(" ", "_").replace("/", "_")[:60] or "dataset"

    left, right = st.columns([3, 2], gap="large")
    with left:
        section("Validation run")
        score = quality_score(report)
        dl(
            [
                ("Dataset", entry.dataset.name),
                ("Format", report.source_format.label),
                ("Generated", report.generated_at.astimezone().strftime("%d %b %Y, %H:%M:%S")),
                ("Profile", report.profile),
                ("Rules run", f"{len(report.rules_run)} in {report.duration_ms:.0f} ms"),
                ("Images / annotations", f"{report.image_count:,} / {report.annotation_count:,}"),
                (
                    "Findings",
                    f"{len(report.issues):,} — " + ", ".join(f"{report.count(s)} {s.value}" for s in Severity),
                ),
                ("Structural / heuristic", f"{summary['structural_findings']} / {summary['heuristic_findings']}"),
                ("Quality score", f"{score:.1f} (heuristic)" if score is not None else "—"),
            ]
        )
        st.html('<div style="height:14px"></div>')
        section("Findings per rule")
        rc = rule_counts(report)
        if rc.empty:
            st.caption("No findings.")
        else:
            st.dataframe(
                rc.rename(
                    columns={
                        "rule_id": "Rule",
                        "rule_name": "Name",
                        "kind": "Kind",
                        "severity": "Severity",
                        "findings": "Findings",
                    }
                ),
                hide_index=True,
                height="auto",
            )
    with right:
        section("Download", "Text cells that start with = + - @ are prefixed with ' to prevent formula injection.")
        st.download_button(
            "Download CSV",
            to_csv(report).encode("utf-8-sig"),
            f"{stem}_labelguard.csv",
            "text/csv",
            icon=":material/table_view:",
            width="stretch",
        )
        st.download_button(
            "Download JSON",
            to_json(report).encode("utf-8"),
            f"{stem}_labelguard.json",
            "application/json",
            icon=":material/data_object:",
            width="stretch",
        )
        st.download_button(
            "Download Excel",
            _xlsx(entry.id, report.generated_at.isoformat()),
            f"{stem}_labelguard.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            icon=":material/grid_on:",
            width="stretch",
        )
        st.caption("Excel workbook sheets: Summary, Issues, Categories, Rules, Configuration.")
        with st.expander("Validation configuration"):
            st.json(report.config, expanded=False)
