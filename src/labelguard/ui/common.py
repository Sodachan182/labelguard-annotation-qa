"""Helpers shared by several pages."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from labelguard.analytics.statistics import issues_frame
from labelguard.models import QualityReport
from labelguard.ui import state
from labelguard.ui.styles import empty_state, esc, severity_text


def require_dataset(action_label: str = "Open Datasets") -> state.Entry | None:
    entry = state.active()
    if entry is None:
        empty_state(
            "No dataset loaded",
            "Load the BDD100K sample or upload CVAT XML, COCO JSON, BDD100K JSON or a ZIP archive "
            "on the Datasets page.",
        )
        if st.button(action_label, type="primary", key="go_datasets"):
            from labelguard.ui.app import go

            go("datasets")
        return None
    return entry


def ensure_report(entry: state.Entry) -> QualityReport:
    if entry.report is None:
        with st.spinner("Running validation"):
            state.run_validation(entry)
    return entry.report  # type: ignore[return-value]


def context_line(entry: state.Entry) -> str:
    r = entry.report
    when = r.generated_at.astimezone().strftime("%d %b %Y, %H:%M") if r else "not validated"
    return (
        f"<b>{esc(entry.dataset.name)}</b> &nbsp;/&nbsp; {esc(entry.dataset.source_format.label)}"
        f" &nbsp;/&nbsp; profile {esc(r.profile if r else '—')} &nbsp;/&nbsp; {esc(when)}"
    )


def table_frame(report: QualityReport) -> pd.DataFrame:
    df = issues_frame(report)
    if df.empty:
        return df
    df = df.copy()
    df["Severity"] = df["severity"].map(severity_text)
    df["Kind"] = df["kind"].str.capitalize()

    def where(r) -> str:
        if pd.notna(r["frame_id"]):
            return f"frame {int(r['frame_id'])}"
        return r["image_name"] or r["image_id"] or "—"

    df["Image / frame"] = df.apply(where, axis=1)
    df["Label"] = df["category"].fillna("").replace("", "—")
    df["Annotation"] = df["annotation_id"].fillna("—")
    return df


ISSUE_COLUMNS = {
    "Severity": st.column_config.TextColumn("Severity", width="small"),
    "rule_id": st.column_config.TextColumn("Rule", width="small"),
    "Image / frame": st.column_config.TextColumn("Image / frame", width="medium"),
    "Label": st.column_config.TextColumn("Label", width="small"),
    "Annotation": st.column_config.TextColumn("Annotation", width="medium"),
    "title": st.column_config.TextColumn("Finding", width="large"),
    "Kind": st.column_config.TextColumn("Kind", width="small"),
}


def open_in_inspector(report: QualityReport, issue_id: str) -> None:
    issue = next((i for i in report.issues if i.issue_id == issue_id), None)
    if issue is None:
        return
    state.select_issue(issue)
    from labelguard.ui.app import go

    go("inspector")
