"""Screen D — Annotation inspector (see .claude/skills/annotation-inspector-ux)."""

from __future__ import annotations

import math
from collections import defaultdict

import streamlit as st

from labelguard.geometry import boxes as B
from labelguard.models import (
    Annotation,
    Dataset,
    ImageRecord,
    QualityIssue,
    Severity,
)
from labelguard.ui import state
from labelguard.ui.common import ensure_report, require_dataset
from labelguard.ui.styles import (
    divider,
    dl,
    empty_state,
    esc,
    kind_html,
    name_html,
    page_header,
    severity_html,
)
from labelguard.ui.theme import SEVERITY_GLYPH, theme_type
from labelguard.visualization.overlays import OverlayOptions, render_overlay

MODES = {"all": "All", "flagged": "Flagged", "selected": "Selected", "none": "Hidden"}
SOURCE_CONVENTION = {
    "coco_instances_json": "COCO [x, y, w, h]",
    "cvat_images_xml": "CVAT xtl, ytl, xbr, ybr",
    "cvat_video_xml": "CVAT xtl, ytl, xbr, ybr",
    "bdd100k_json": "BDD100K box2d x1, y1, x2, y2 (inclusive)",
}


# ------------------------------------------------------------------- indexes


def _index(entry: state.Entry) -> dict:
    """Per-dataset lookups, rebuilt only when the report changes."""
    cache = st.session_state.setdefault("lg_insp_cache", {})
    key = (entry.id, entry.report.generated_at if entry.report else None)
    if key in cache:
        return cache[key]
    ds, report = entry.dataset, entry.report
    by_image: dict[str, list[Annotation]] = defaultdict(list)
    for a in ds.annotations:
        by_image[a.image_id].append(a)
    issues_by_image: dict[str, list[QualityIssue]] = defaultdict(list)
    order = {img.id: n for n, img in enumerate(ds.images)}
    for i in report.issues:
        if i.image_id:
            issues_by_image[i.image_id].append(i)
    walk = sorted(
        (i for i in report.issues if i.image_id in order), key=lambda i: (order[i.image_id], i.severity.rank, i.rule_id)
    )
    cache.clear()
    cache[key] = {
        "by_image": by_image,
        "issues_by_image": issues_by_image,
        "walk": walk,
        "order": order,
        "by_id": {i.issue_id: i for i in report.issues},
    }
    return cache[key]


def _image_list(ds: Dataset, idx: dict) -> list[ImageRecord]:
    if state.prefs().get("images_with_findings_only"):
        imgs = [img for img in ds.images if idx["issues_by_image"].get(img.id)]
        return imgs or ds.images
    return ds.images


# ---------------------------------------------------------------- navigation


def _select_issue(issue: QualityIssue | None) -> None:
    if issue is None:
        return
    state.select_issue(issue)


def _step_issue(walk: list[QualityIssue], delta: int) -> None:
    if not walk:
        return
    cur = st.session_state.lg_selected_issue
    ids = [i.issue_id for i in walk]
    if cur in ids:
        n = (ids.index(cur) + delta) % len(ids)
    else:
        img = st.session_state.lg_inspector_image
        after = [k for k, i in enumerate(walk) if i.image_id == img]
        n = after[0] if after and delta > 0 else (after[-1] if after else 0)
    _select_issue(walk[n])


def _step_image(images: list[ImageRecord], delta: int) -> None:
    ids = [i.id for i in images]
    cur = st.session_state.lg_inspector_image
    n = (ids.index(cur) + delta) % len(ids) if cur in ids else 0
    st.session_state.lg_inspector_image = ids[n]
    state.clear_selection()


def _clear() -> None:
    state.clear_selection()


def _on_image_pick() -> None:
    """Dropdown callback. Runs before the script, so the page renders the picked image."""
    st.session_state.lg_inspector_image = st.session_state["w_insp_img"]
    state.clear_selection()


def _pick_annotation(ann_id: str) -> None:
    st.session_state.lg_selected_issue = None
    st.session_state.lg_selected_annotation = ann_id


def _pick_issue(issue_id: str, by_id: dict) -> None:
    _select_issue(by_id.get(issue_id))


# -------------------------------------------------------------------- panels


def _coords_table(ann: Annotation) -> str:
    rows = []
    if ann.bbox is not None:
        src = ann.bbox_source or ann.bbox
        conv = SOURCE_CONVENTION.get(ann.source_format.value, "Source")
        fmt = lambda vals: "".join(  # noqa: E731
            f"<td title='{v}'>{v:.1f}</td>" if isinstance(v, float) and math.isfinite(v) else f"<td>{esc(v)}</td>"
            for v in vals
        )
        rows.append(f"<tr><td title='{esc(conv)}'>Source</td>{fmt(src)}</tr>")
        rows.append(f"<tr><td title='Continuous pixel corners used by every rule'>Normalized</td>{fmt(ann.bbox)}</tr>")
        if B.is_finite(ann.bbox):
            w, h = B.width_height(ann.bbox)
            rows.append(f"<tr><td>W × H</td><td colspan='2'>{w:.1f}</td><td colspan='2'>{h:.1f}</td></tr>")
    elif ann.polygons:
        ext = ann.extent()
        rows.append(f"<tr><td>Vertices</td><td colspan='4'>{sum(len(r) for r in ann.polygons)}</td></tr>")
        if ext:
            rows.append("<tr><td>Extent</td>" + "".join(f"<td>{v:.1f}</td>" for v in ext) + "</tr>")
    elif ann.points:
        rows.append(f"<tr><td>Points</td><td colspan='4'>{len(ann.points)}</td></tr>")
    if not rows:
        return ""
    head = "<tr><th></th><th>x1</th><th>y1</th><th>x2</th><th>y2</th></tr>" if ann.bbox is not None else ""
    return f'<table class="lg-coords">{head}{"".join(rows)}</table>'


def _details(
    issue: QualityIssue | None, ann: Annotation | None, img: ImageRecord, img_issues: list[QualityIssue]
) -> None:
    facts: list[tuple[str, str]] = []
    if issue is not None:
        st.html(
            f"{severity_html(issue.severity.value)}{kind_html(issue.kind.value)}"
            f'<div class="lg-finding-title">{esc(issue.title)}</div>'
            f'<p class="lg-explain">{esc(issue.description)}</p>'
            f'<div class="lg-action">{esc(issue.suggested_action)}</div>'
        )
        facts = [("Rule", f"{issue.rule_id} {issue.rule_name}"), ("Finding id", issue.issue_id)]
        if ann is None:
            dl(facts)
    elif ann is not None:
        mine = [i for i in img_issues if i.annotation_id == ann.id]
        status = f"{len(mine)} finding(s) on this object" if mine else "No findings on this object"
        st.html(
            f'<div class="lg-finding-title">{esc(ann.category or "Unlabelled")} '
            f'<span class="lg-kind">#{esc(ann.id)}</span></div><p class="lg-explain">{esc(status)}</p>'
        )
    else:
        attrs = img.raw.get("attributes") or {}
        meta = [(k.capitalize(), str(v)) for k, v in attrs.items() if v not in ("", None)]
        st.html(
            '<div class="lg-finding-title">Image</div>'
            '<p class="lg-explain">Select a finding or an object to see its geometry and evidence.</p>'
        )
        size = f"{img.width:g} × {img.height:g} px" if img.has_valid_size else "invalid"
        dl(
            [
                ("File", name_html(img.file_name, 30)),
                ("Size", esc(size)),
                ("Size source", esc(img.raw.get("size_source", "annotation file"))),
                *[(k, esc(v)) for k, v in meta],
                ("Findings", str(len(img_issues))),
            ],
            raw=True,
        )
        return
    if ann is not None:
        facts += [("Label", ann.category or "—"), ("Geometry", ann.geometry_type.value), ("Annotation", ann.id)]
        if ann.track_id is not None:
            facts.append(("Track", ann.track_id))
        if ann.frame is not None:
            facts.append(("Frame", str(ann.frame)))
        facts += [(k, v) for k, v in ann.attributes.items()][:6]
        dl(facts)
        table = _coords_table(ann)
        if table:
            conv = SOURCE_CONVENTION.get(ann.source_format.value, "")
            st.html(f'<div class="lg-caption" style="margin:12px 0 4px">Coordinates. Source: {esc(conv)}</div>{table}')
        st.html(
            f'<div class="lg-caption" style="margin-top:10px">Source</div>'
            f'<div class="lg-mono">{esc(ann.source_location)}</div>'
        )
    if issue is not None:
        with st.expander("Raw evidence"):
            st.json(issue.evidence, expanded=True)


# ---------------------------------------------------------------------- page


def render() -> None:
    entry = state.active()
    if entry is None:
        page_header("Inspector", "Review findings on the image they belong to.")
        divider()
        require_dataset()
        return
    ensure_report(entry)
    ds = entry.dataset
    idx = _index(entry)
    prefs = state.prefs()
    ss = st.session_state

    images = _image_list(ds, idx)
    if not images:
        page_header("Inspector", "Review findings on the image they belong to.")
        divider()
        empty_state("This dataset has no images", "Nothing to inspect.")
        return
    ids = [i.id for i in images]
    if ss.lg_inspector_image not in idx["order"]:
        first = idx["walk"][0].image_id if idx["walk"] else ids[0]
        ss.lg_inspector_image = first
    img = next((i for i in ds.images if i.id == ss.lg_inspector_image), images[0])
    pos = ids.index(img.id) + 1 if img.id in ids else None
    unit = "Frame" if ds.is_video else "Image"
    counter = f"{unit} {pos} of {len(ids)}" if pos else f"{unit} not in the filtered list"
    img_issues = sorted(idx["issues_by_image"].get(img.id, []), key=lambda i: (i.severity.rank, i.rule_id))
    page_header(
        "Inspector",
        "Review each finding on the image it belongs to.",
        f"<b>{name_html(img.file_name, 64)}</b> &nbsp;/&nbsp; {esc(counter)} &nbsp;/&nbsp; "
        f"{len(img_issues)} finding{'s' if len(img_issues) != 1 else ''} on this {unit.lower()}",
    )

    # ---- toolbar
    t1, t2, t3 = st.columns([2.4, 1.6, 2.0], vertical_alignment="bottom")
    ss["w_insp_img"] = img.id if img.id in ids else ids[0]
    counts = {k: len(v) for k, v in idx["issues_by_image"].items()}
    names = {x.id: x.file_name for x in images}
    row = t1.container(horizontal=True, vertical_alignment="bottom", gap="small", key="imgnav")
    row.selectbox(
        unit,
        ids,
        key="w_insp_img",
        on_change=_on_image_pick,
        format_func=lambda i: names[i] + (f"  ({counts[i]} findings)" if counts.get(i) else ""),
    )
    row.button(
        f"Previous {unit.lower()}",
        icon=":material/chevron_left:",
        shortcut="Shift+Left",
        key="nav_prev_img",
        help=f"Previous {unit.lower()} (Shift+←)",
        on_click=_step_image,
        args=(images, -1),
    )
    row.button(
        f"Next {unit.lower()}",
        icon=":material/chevron_right:",
        shortcut="Shift+Right",
        key="nav_next_img",
        help=f"Next {unit.lower()} (Shift+→)",
        on_click=_step_image,
        args=(images, 1),
    )
    ss.setdefault("w_insp_mode", prefs["overlay_mode"])
    mode = t2.segmented_control("Overlay", list(MODES), format_func=MODES.get, key="w_insp_mode") or "all"
    anns = idx["by_image"].get(img.id, [])
    classes = sorted({a.category for a in anns if a.category})
    shown_classes = t3.multiselect("Classes", classes, placeholder="All classes", key=f"w_insp_cls_{entry.id}")
    o1, o2, o3, o4 = st.columns(4)
    ss.setdefault("w_insp_labels", prefs["show_labels"])
    ss.setdefault("w_insp_ids", prefs["show_ids"])
    ss.setdefault("w_insp_zoom", prefs["zoom_to_selection"])
    ss.setdefault("w_insp_only", prefs["images_with_findings_only"])
    show_labels = o1.toggle("Labels", key="w_insp_labels")
    show_ids = o2.toggle("Annotation ids", key="w_insp_ids")
    zoom = o3.toggle("Zoom to selection", key="w_insp_zoom")
    only = o4.toggle("Only images with findings", key="w_insp_only")
    if only != prefs["images_with_findings_only"]:
        prefs["images_with_findings_only"] = only
        st.rerun()

    sel_issue = idx["by_id"].get(ss.lg_selected_issue)
    if sel_issue is not None and sel_issue.image_id != img.id:
        sel_issue = None
    sel_ann_id = sel_issue.annotation_id if sel_issue else ss.lg_selected_annotation
    sel_ann = next((a for a in anns if a.id == sel_ann_id), None)

    left, center, right = st.columns([0.95, 2.9, 1.3], gap="medium")

    # ---- left: findings / objects
    with left:
        tab_f, tab_o = st.tabs([f"Findings ({len(img_issues)})", f"Objects ({len(anns)})"])
        with tab_f, st.container(height=560, border=False, key="findings-list"):
            if not img_issues:
                st.caption(f"No findings on this {unit.lower()}.")
            for n, i in enumerate(img_issues):
                icon = {"critical": ":material/error:", "warning": ":material/warning:", "info": ":material/info:"}
                st.button(
                    f"**{i.rule_id}** {i.title}  \n{SEVERITY_GLYPH[i.severity.value]} {i.severity.label}"
                    f" · {i.annotation_id or 'image-level'}",
                    key=f"fi_{i.severity.value}_{n}",
                    icon=icon[i.severity.value],
                    width="stretch",
                    type="primary" if sel_issue and sel_issue.issue_id == i.issue_id else "secondary",
                    on_click=_pick_issue,
                    args=(i.issue_id, idx["by_id"]),
                )
        with tab_o, st.container(height=560, border=False, key="objects-list"):
            flagged = {i.annotation_id for i in img_issues}
            visible_anns = [a for a in anns if not shown_classes or a.category in shown_classes]
            if not visible_anns:
                st.caption("No objects.")
            for a in visible_anns[:400]:
                mark = " ·  flagged" if a.id in flagged else ""
                st.button(
                    f"{a.category or 'unlabelled'}  #{a.id.split(':')[-1]}{mark}",
                    key=f"ob_{a.id}",
                    width="stretch",
                    type="primary" if sel_ann and sel_ann.id == a.id else "secondary",
                    on_click=_pick_annotation,
                    args=(a.id,),
                )

    # ---- center: canvas + navigation
    with center:
        sev_map: dict[str, Severity] = {}
        for i in img_issues:
            if i.annotation_id and (i.annotation_id not in sev_map or i.severity.rank < sev_map[i.annotation_id].rank):
                sev_map[i.annotation_id] = i.severity
        draw = [a for a in anns if not shown_classes or a.category in shown_classes or (sel_ann and a.id == sel_ann.id)]
        result = render_overlay(
            img,
            draw,
            image_path=ds.image_paths.get(img.id),
            severities=sev_map,
            selected_id=sel_ann.id if sel_ann else None,
            categories=[c.name for c in ds.categories],
            options=OverlayOptions(
                mode=mode,
                show_labels=show_labels and len(draw) <= 120,
                show_ids=show_ids,
                zoom_to_selection=zoom and sel_ann is not None,
                target_width=int(prefs["canvas_resolution"]),
                theme=theme_type(),
            ),
        )
        with st.container(key="canvas"):
            st.image(result.image, width="stretch", output_format="JPEG" if result.has_pixels else "PNG")
        notes = []
        if not result.has_pixels:
            notes.append("Source image not available. Showing annotation geometry on a blank canvas.")
        else:
            notes.append(f"{result.pixel_size[0]} × {result.pixel_size[1]} px source")
        if result.size_mismatch:
            dw, dh = result.declared_size
            notes.append(f"declared size {dw:g} × {dh:g} differs from the file")
        notes.append(f"{result.drawn} of {len(anns)} objects drawn")
        if show_labels and len(draw) > 120:
            notes.append("labels hidden in dense scenes")
        attrs = img.raw.get("attributes") or {}
        notes += [str(v) for k, v in attrs.items() if k in ("timeofday", "weather", "scene") and v]
        st.html(f'<div class="lg-caption">{" · ".join(esc(n) for n in notes)}</div>')
        walk = idx["walk"]
        nav = st.container(horizontal=True, gap="small", horizontal_alignment="distribute")
        nav.button(
            "Previous finding",
            icon=":material/chevron_left:",
            shortcut="Left",
            on_click=_step_issue,
            args=(walk, -1),
            disabled=not walk,
        )
        nav.button(
            "Clear selection",
            shortcut="Esc",
            on_click=_clear,
            type="tertiary",
            disabled=sel_ann is None and sel_issue is None,
        )
        nav.button(
            "Next finding",
            icon=":material/chevron_right:",
            icon_position="right",
            shortcut="Right",
            on_click=_step_issue,
            args=(walk, 1),
            disabled=not walk,
        )

    # ---- right: details
    with right, st.container(border=True, key="details"):
        _details(sel_issue, sel_ann, img, img_issues)
