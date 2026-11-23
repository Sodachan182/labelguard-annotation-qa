"""Screen C — Issue explorer."""

from __future__ import annotations

import streamlit as st

from labelguard.ui import state
from labelguard.ui.common import (
    ISSUE_COLUMNS,
    context_line,
    ensure_report,
    open_in_inspector,
    require_dataset,
    table_frame,
)
from labelguard.ui.filters import filter_issues
from labelguard.ui.styles import (
    divider,
    dl,
    empty_state,
    esc,
    kind_html,
    page_header,
    severity_html,
)


def render() -> None:
    entry = state.active()
    page_header(
        "Issues",
        "Every finding from the last validation run. Structural findings are format or geometry "
        "violations; heuristic findings are suspicious but valid data that needs a human decision.",
        context_line(entry) if entry else None,
    )
    divider()
    entry = require_dataset()
    if entry is None:
        return
    report = ensure_report(entry)
    df = table_frame(report)
    if df.empty:
        empty_state(
            "No findings",
            "Every enabled rule passed on this dataset. Adjust thresholds in Settings "
            "to make heuristic checks stricter.",
        )
        return

    f1, f2, f3, f4 = st.columns([1.3, 1.1, 1.4, 1.2])
    sev = f1.pills("Severity", ["Critical", "Warning", "Info"], selection_mode="multi", key="w_f_sev")
    kind = f2.pills("Kind", ["Structural", "Heuristic"], selection_mode="multi", key="w_f_kind")
    rules = f3.multiselect(
        "Rule",
        sorted(df["rule_id"].unique()),
        key="w_f_rule",
        format_func=lambda r: f"{r} {df.loc[df['rule_id'] == r, 'rule_name'].iloc[0]}",
    )
    cats = f4.multiselect("Label", sorted(c for c in df["category"].dropna().unique() if c), key="w_f_cat")
    g1, g2 = st.columns([1.3, 2.4])
    images = ["All images", *sorted(df["image_name"].dropna().unique().tolist())]
    img = g1.selectbox("Image / frame", images, key="w_f_img")
    query = g2.text_input("Search", placeholder="Search titles, descriptions, ids", key="w_f_q")

    view = filter_issues(df, sev or [], kind or [], rules, cats, None if img == "All images" else img, query)
    st.caption(f"Showing {len(view):,} of {len(df):,} findings")
    if view.empty:
        empty_state("No findings match these filters", "Clear a filter or the search text to see more.")
        return
    ev = st.dataframe(
        view[list(ISSUE_COLUMNS)],
        column_config=ISSUE_COLUMNS,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="iss_table",
        height="auto" if len(view) <= 12 else 520,
    )
    rows = ev.selection.rows if ev else []
    if not rows:
        st.caption("Select a row to see evidence and the suggested action.")
        return
    row = view.iloc[rows[0]]
    issue = next(i for i in report.issues if i.issue_id == row["issue_id"])
    with st.container(border=True, key="issue-detail"):
        a, b = st.columns([3, 2], gap="large")
        with a:
            st.html(
                f"{severity_html(issue.severity.value)}{kind_html(issue.kind.value)}"
                f'<div class="lg-finding-title">{esc(issue.title)}</div>'
                f'<p class="lg-explain">{esc(issue.description)}</p>'
                f'<div class="lg-action">{esc(issue.suggested_action)}</div>'
            )
            if st.button("Open in Inspector", type="primary", icon=":material/center_focus_strong:"):
                open_in_inspector(report, issue.issue_id)
        with b:
            dl(
                [
                    ("Rule", f"{issue.rule_id} {issue.rule_name}"),
                    ("Image", issue.image_name or issue.image_id or "—"),
                    ("Annotation", issue.annotation_id or "—"),
                    ("Label", issue.category or "—"),
                    ("Source", issue.source_location or "—"),
                    ("Finding id", issue.issue_id),
                ]
            )
            with st.expander("Evidence"):
                st.json(issue.evidence, expanded=True)
