"""Screen B — Dataset management."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from labelguard.benchmark.bdd100k_source import LICENSE_NOTICE
from labelguard.ui import state
from labelguard.ui.styles import divider, dl, empty_state, page_header, section

ACCEPT = ["xml", "json", "zip", "jpg", "jpeg", "png"]


def _upload_panel(expanded_copy: bool) -> None:
    with st.container(border=True, key="upload-panel"):
        if expanded_copy:
            empty_state(
                "Start with a dataset",
                "Upload CVAT XML, COCO JSON, BDD100K JSON or a ZIP archive to begin annotation quality "
                "analysis. Add the image files to see overlays on real pixels.",
            )
        files = st.file_uploader(
            "Annotation files, images or a ZIP archive",
            type=ACCEPT,
            accept_multiple_files=True,
            key="w_upload",
            help="Files are copied into a temporary session folder; originals are not modified.",
        )
        cols = st.columns([1, 1, 2])
        if cols[0].button("Import files", type="primary", disabled=not files, icon=":material/upload:"):
            folder = state.save_uploads(files)
            zips = [f for f in folder.iterdir() if f.suffix.lower() == ".zip"]
            target = zips[0] if len(zips) == 1 and len(list(folder.iterdir())) == 1 else folder
            with st.spinner("Parsing and validating"):
                added, errors = state.add_from_path(
                    target,
                    f"Upload ({len(files)} file{'s' if len(files) != 1 else ''})",
                    origin={"path": str(target), "images_dir": None, "session_copy": str(folder)},
                )
            st.session_state.lg_import_errors = errors
            if added or errors:
                st.toast(f"Imported {len(added)} dataset{'s' if len(added) != 1 else ''}")
                st.rerun()
        subsets = state.bdd_subsets()
        if subsets:
            choice = cols[1].selectbox("BDD100K subset", subsets, label_visibility="collapsed", key="w_bdd_profile")
            if cols[2].button("Load BDD100K sample", icon=":material/directions_car:"):
                with st.spinner("Loading real BDD100K images and labels"):
                    st.session_state.lg_import_errors = state.load_bdd_sample(choice)
                st.rerun()
        else:
            st.caption(
                "No local BDD100K subset yet. Download 20 real validation images with their original labels "
                "(about 2 MB, plus 17 MB of metadata used for sampling):"
            )
            st.code(
                "labelguard bdd100k fetch --profile smoke --accept-license\n"
                "labelguard bdd100k benchmark --profile smoke",
                language="powershell",
            )
        st.caption(LICENSE_NOTICE)


def render() -> None:
    entries = state.entries()
    page_header("Datasets", "Import, validate and manage annotation datasets.")
    divider()
    for err in st.session_state.pop("lg_import_errors", []):
        st.error(err)
    if not entries:
        _upload_panel(expanded_copy=True)
        return

    section("Loaded datasets", "Select a row to see details and actions.")
    rows = []
    for e in entries.values():
        r = e.report
        rows.append(
            {
                "id": e.id,
                "Name": e.dataset.name,
                "Format": e.dataset.source_format.label,
                "Imported": e.imported_at.strftime("%d %b %H:%M"),
                "Images": len(e.dataset.images),
                "With pixels": len(e.dataset.image_paths),
                "Annotations": len(e.dataset.annotations),
                "Parsing": "Warnings" if e.dataset.parse_warnings else "OK",
                "Validation": e.validation_status,
                "Findings": len(r.issues) if r else None,
                "Active": "●" if e.id == st.session_state.lg_active else "",
            }
        )
    df = pd.DataFrame(rows)
    ev = st.dataframe(
        df.drop(columns=["id"]),
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="ds_table",
        column_config={
            "Active": st.column_config.TextColumn("", width=28),
            "Name": st.column_config.TextColumn(width="large"),
            "Findings": st.column_config.NumberColumn(format="%d"),
        },
    )
    sel = [r for r in (ev.selection.rows if ev else []) if r < len(df)]
    chosen = entries[df.iloc[sel[0]]["id"]] if sel else state.active()
    if chosen is not None:
        st.html('<div style="height:8px"></div>')
        left, right = st.columns([3, 2], gap="large")
        with left:
            section(chosen.dataset.name)
            ds = chosen.dataset
            dl(
                [
                    ("Source", chosen.source),
                    ("Format", ds.source_format.label),
                    ("Dataset id", ds.id),
                    ("Images with pixels", f"{len(ds.image_paths)} of {len(ds.images)}"),
                    ("Categories", ", ".join(c.name for c in ds.categories) or "not declared"),
                    ("Parse notes", " ".join(ds.parse_warnings) or "None"),
                ]
            )
        with right:
            section("Actions")
            bar = st.container(horizontal=True, gap="small")
            if bar.button("Set active", disabled=chosen.id == st.session_state.lg_active):
                state.set_active(chosen.id)
                st.rerun()
            if bar.button("Run validation", icon=":material/play_arrow:"):
                with st.spinner("Running validation"):
                    state.run_validation(chosen)
                st.toast("Validation finished")
                st.rerun()
            if bar.button("Re-import", icon=":material/refresh:"):
                for err in state.reimport(chosen):
                    st.error(err)
                st.rerun()
            confirm = st.checkbox("Confirm removal from this session", key="w_rm_confirm")
            if st.button("Remove dataset", disabled=not confirm, icon=":material/delete:"):
                state.remove(chosen.id)
                st.toast("Dataset removed from the session. Files on disk were not touched.")
                st.rerun()
    divider()
    with st.expander("Add dataset", expanded=False):
        _upload_panel(expanded_copy=False)
