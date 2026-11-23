"""Screen A — Dataset overview."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from labelguard.analytics.statistics import (
    SCORE_WEIGHTS,
    box_sizes,
    category_counts,
    quality_score,
    rule_counts,
    severity_counts,
)
from labelguard.models import Severity
from labelguard.ui import state
from labelguard.ui.common import (
    ISSUE_COLUMNS,
    context_line,
    ensure_report,
    open_in_inspector,
    require_dataset,
    table_frame,
)
from labelguard.ui.styles import divider, dl, metric_strip, page_header, section
from labelguard.ui.theme import PLOTLY_CONFIG, plotly_layout, tokens


def _hbar(labels, values, colors, x_title: str, height: int | None = None):
    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker={"color": colors, "line": {"width": 0}},
            hovertemplate="%{y}: %{x}<extra></extra>",
            text=values,
            textposition="outside",
            cliponaxis=False,
            textfont={"size": 11},
        )
    )
    lay = plotly_layout(height or max(150, 28 * len(labels) + 50))
    lay["xaxis"]["title"]["text"] = x_title
    lay["xaxis"]["tickformat"] = ",d"
    peak = max(list(values) or [0])
    if peak <= 5:
        lay["xaxis"].update(dtick=1, range=[0, max(peak, 1) * 1.15])
    lay["yaxis"]["autorange"] = "reversed"
    fig.update_layout(**lay)
    return fig


def render() -> None:
    entry = state.active()
    actions = page_header(
        "Dataset overview",
        "Annotation quality analysis and validation results.",
        context_line(entry) if entry else None,
    )
    if actions.button("Upload dataset", icon=":material/upload:"):
        from labelguard.ui.app import go as nav

        nav("datasets")
    run = actions.button("Run validation", icon=":material/play_arrow:", disabled=entry is None)
    if actions.button("Export report", icon=":material/download:", disabled=entry is None):
        from labelguard.ui.app import go as nav

        nav("reports")
    divider()
    entry = require_dataset()
    if entry is None:
        return
    if run:
        bar = st.progress(0.0, text="Running validation")
        state.run_validation(entry, progress=lambda f, label: bar.progress(min(f, 1.0), text=label))
        bar.empty()
        st.toast("Validation finished")
    report = ensure_report(entry)
    ds = entry.dataset
    t = tokens()

    critical = report.count(Severity.CRITICAL)
    unit = "Frames" if ds.is_video else "Images"
    flagged = len(report.flagged_annotation_ids)
    metric_strip(
        [
            (unit, f"{len(ds.images):,}", f"{len(ds.image_paths):,} with pixels", ""),
            ("Annotations", f"{len(ds.annotations):,}", f"{len(ds.categories)} categories", ""),
            ("Findings", f"{len(report.issues):,}", f"{flagged:,} annotation{'' if flagged == 1 else 's'} flagged", ""),
            (
                "Critical",
                f"{critical:,}",
                "structural defects" if critical else "none found",
                "critical" if critical else "",
            ),
        ]
    )

    st.html('<div style="height:20px"></div>')
    c1, c2 = st.columns(2, gap="large")
    with c1:
        section("Annotations by category")
        cc = category_counts(ds).head(15)
        if cc.empty:
            st.caption("No annotations.")
        else:
            st.plotly_chart(
                _hbar(cc["category"], cc["annotations"], t["accent"], "Annotations"), config=PLOTLY_CONFIG, key="ch_cat"
            )
    with c2:
        section("Findings by severity")
        sc = severity_counts(report)
        if not report.issues:
            st.caption("No findings. Every enabled rule passed on this dataset.")
        else:
            st.plotly_chart(
                _hbar(list(sc), list(sc.values()), [t["critical"], t["warning"], t["info"]], "Findings", 170),
                config=PLOTLY_CONFIG,
                key="ch_sev",
            )

    c3, c4 = st.columns(2, gap="large")
    with c3:
        section("Findings by rule")
        rc = rule_counts(report).head(10)
        if rc.empty:
            st.caption("No rule produced a finding.")
        else:
            labels = [f"{r.rule_id}  {r.rule_name}" for r in rc.itertuples()]
            colors = [t[s] for s in rc["severity"]]
            st.plotly_chart(_hbar(labels, rc["findings"], colors, "Findings"), config=PLOTLY_CONFIG, key="ch_rule")
    with c4:
        section("Object size", "√(box area ÷ image area), as a percentage of the image side.")
        bs = box_sizes(ds)
        if bs.empty or bs["relative_size"].isna().all():
            st.caption("No sized boxes.")
        else:
            fig = go.Figure(
                go.Histogram(
                    x=bs["relative_size"].dropna() * 100,
                    nbinsx=40,
                    marker={"color": t["accent"], "line": {"width": 0}},
                    hovertemplate="%{x:.1f}%: %{y} boxes<extra></extra>",
                )
            )
            lay = plotly_layout(240)
            lay["xaxis"]["title"]["text"] = "Relative size (%)"
            lay["yaxis"]["title"]["text"] = "Boxes"
            lay["yaxis"]["gridcolor"] = t["border"]
            fig.update_layout(**lay)
            st.plotly_chart(fig, config=PLOTLY_CONFIG, key="ch_size")

    divider()
    left, right = st.columns([1, 2], gap="large")
    with left:
        section("Dataset health")
        score = quality_score(report)
        structural = sum(1 for i in report.issues if i.kind.value == "structural")
        dl(
            [
                ("Format", ds.source_format.label),
                (unit, f"{len(ds.images):,}"),
                ("Annotations", f"{len(ds.annotations):,}"),
                (
                    "Classes",
                    ", ".join(category_counts(ds)["category"].head(6)) + (" …" if len(ds.categories) > 6 else ""),
                ),
                ("Validation", f"{len(report.rules_run)} rules in {report.duration_ms:.0f} ms"),
                ("Profile", report.profile),
                ("Structural / heuristic", f"{structural} / {len(report.issues) - structural}"),
                ("Quality score", f"{score:.1f} / 100" if score is not None else "—"),
            ]
        )
        st.caption(
            f"Quality score is a LabelGuard heuristic: 100 × (1 − Σ penalty ÷ annotations), "
            f"penalty {SCORE_WEIGHTS[Severity.CRITICAL]:g} for an annotation with a critical finding and "
            f"{SCORE_WEIGHTS[Severity.WARNING]:g} for a warning. It ranks runs; it does not measure label truth."
        )
        for w in ds.parse_warnings:
            st.caption(f"Note: {w}")
    with right:
        section("Recent findings", "Critical and warning findings first. Select a row to inspect it.")
        df = table_frame(report)
        if df.empty:
            st.caption("Nothing to review.")
        else:
            top = df[df["severity"] != "info"].head(12)
            if top.empty:
                top = df.head(12)
            ev = st.dataframe(
                top[list(ISSUE_COLUMNS)],
                column_config=ISSUE_COLUMNS,
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                key=f"ov_table_{entry.id}_{report.generated_at.timestamp():.0f}",
                height="auto",
            )
            rows = [r for r in (ev.selection.rows if ev else []) if r < len(top)]
            if rows:
                issue_id = top.iloc[rows[0]]["issue_id"]
                if st.button("Open in Inspector", type="primary", icon=":material/center_focus_strong:"):
                    open_in_inspector(report, issue_id)
