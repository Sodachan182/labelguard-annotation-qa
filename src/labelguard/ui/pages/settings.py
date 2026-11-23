"""Screen F — Settings."""

from __future__ import annotations

import streamlit as st

from labelguard import __version__
from labelguard.config import PROFILES, ValidationConfig
from labelguard.ui import state
from labelguard.ui.styles import divider, dl, page_header, section
from labelguard.ui.theme import theme_type
from labelguard.validation.engine import all_rules


def _validation_form(cfg: ValidationConfig) -> ValidationConfig | None:
    rules = all_rules()
    with st.form("validation-settings", border=False):
        profile = st.selectbox(
            "Rule profile",
            list(PROFILES),
            index=list(PROFILES).index(cfg.profile),
            format_func=lambda p: PROFILES[p].name,
            help="Changing the profile and saving resets thresholds to that profile's defaults.",
        )
        st.caption(PROFILES[profile].description)
        enabled_now = [
            r.id
            for r in rules
            if r.id not in cfg.disabled_rules and (cfg.enabled_rules is None or r.id in cfg.enabled_rules)
        ]
        enabled = st.multiselect(
            "Enabled rules",
            [r.id for r in rules],
            default=enabled_now,
            format_func=lambda rid: f"{rid} {next(r.name for r in rules if r.id == rid)}",
        )
        st.html('<div class="lg-section">Bounding boxes</div>')
        b = cfg.boxes
        c1, c2, c3 = st.columns(3)
        b_tol = c1.number_input("Bounds tolerance (px)", 0.0, 50.0, float(b.bounds_tolerance_px), 0.5)
        b_area = c2.number_input("Minimum area (px²)", 0.0, 10_000.0, float(b.min_area_px), 4.0)
        b_side = c3.number_input("Minimum side (px)", 0.0, 200.0, float(b.min_side_px), 1.0)
        c4, c5, c6 = st.columns(3)
        b_aspect = c4.number_input("Maximum aspect ratio", 1.5, 200.0, float(b.max_aspect_ratio), 0.5)
        b_dup = c5.slider("Duplicate IoU (same label)", 0.5, 1.0, float(b.duplicate_iou), 0.01)
        b_conf = c6.slider("Conflict IoU (different labels)", 0.5, 1.0, float(b.conflict_iou), 0.01)
        st.html('<div class="lg-section">Polygons and keypoints</div>')
        p1, p2, p3 = st.columns(3)
        p_tol = p1.number_input(
            "Polygon bounds tolerance (px)", 0.0, 50.0, float(cfg.polygons.bounds_tolerance_px), 0.5
        )
        p_area = p2.number_input("Polygon minimum area (px²)", 0.0, 10_000.0, float(cfg.polygons.min_area_px), 4.0)
        k_margin = p3.number_input(
            "Keypoint margin outside box (ratio)", 0.0, 5.0, float(cfg.keypoints.bbox_margin_ratio), 0.05
        )
        st.html('<div class="lg-section">Video tracks</div>')
        v1, v2, v3, v4 = st.columns(4)
        t = cfg.tracks
        t_jump = v1.number_input("Max jump (diagonals / frame)", 0.05, 10.0, float(t.max_jump_ratio), 0.05)
        t_scale = v2.number_input("Max area change / frame", 1.05, 20.0, float(t.max_scale_change), 0.05)
        t_policy = v3.selectbox(
            "Gap policy",
            ["interpolated", "explicit"],
            index=["interpolated", "explicit"].index(t.gap_policy),
            help="'interpolated' follows CVAT: gaps between keyframes are valid.",
        )
        t_gap = v4.number_input("Max gap (frames)", 1, 10_000, int(t.max_gap), 1)
        submitted = st.form_submit_button("Save validation settings", type="primary")
    if not submitted:
        return None
    if profile != cfg.profile:
        new = ValidationConfig.for_profile(profile)
    else:
        new = cfg.model_copy(deep=True)
        new.boxes = new.boxes.model_copy(
            update={
                "bounds_tolerance_px": b_tol,
                "min_area_px": b_area,
                "min_side_px": b_side,
                "max_aspect_ratio": b_aspect,
                "duplicate_iou": b_dup,
                "conflict_iou": b_conf,
            }
        )
        new.polygons = new.polygons.model_copy(update={"bounds_tolerance_px": p_tol, "min_area_px": p_area})
        new.keypoints = new.keypoints.model_copy(update={"bbox_margin_ratio": k_margin})
        new.tracks = new.tracks.model_copy(
            update={
                "max_jump_ratio": t_jump,
                "max_scale_change": t_scale,
                "gap_policy": t_policy,
                "max_gap": int(t_gap),
            }
        )
    new.enabled_rules = None
    new.disabled_rules = sorted({r.id for r in rules} - set(enabled))
    return ValidationConfig.model_validate(new.model_dump())


def render() -> None:
    page_header("Settings", "Validation rules, thresholds and inspector defaults.")
    divider()
    tab_g, tab_v, tab_i, tab_a = st.tabs(["General", "Validation", "Inspector", "About"])

    with tab_g:
        section("Appearance")
        st.write(
            f"LabelGuard follows the theme chosen in the app menu (⋮ › Settings › Theme). "
            f"Current theme: **{theme_type()}**. Both themes use the same layout and severity glyphs."
        )
        section("Storage")
        dl(
            [
                ("Settings file", str(state.SETTINGS_FILE)),
                ("Session folder", str(st.session_state.lg_workdir)),
                ("Real-data folder", str(state.DATA_ROOT)),
            ]
        )
        st.caption("Uploads are copied into the session folder. Original files are never modified.")
        section("Start-up")
        restore = state.prefs().get("restore_bdd_profile")
        if restore:
            st.write(f"The BDD100K **{restore}** sample is reloaded when a new browser session starts.")
            if st.button("Start with an empty workspace instead"):
                state.prefs()["restore_bdd_profile"] = None
                state.save_settings()
                st.rerun()
        else:
            st.write("New browser sessions start with an empty workspace.")

    with tab_v:
        new = _validation_form(state.config())
        if new is not None:
            state.set_config(new)
            err = state.save_settings()
            if err:
                st.error(err)
            for e in state.entries().values():
                state.run_validation(e)
            st.success(f"Saved. Re-validated {len(state.entries())} loaded dataset(s) with profile '{new.profile}'.")
        if st.button("Reset to profile defaults"):
            state.set_config(ValidationConfig.for_profile(state.config().profile))
            state.save_settings()
            st.rerun()

    with tab_i:
        p = state.prefs()
        with st.form("inspector-settings", border=False):
            modes = ["all", "flagged", "selected", "none"]
            mode = st.selectbox(
                "Default overlay",
                modes,
                index=modes.index(p["overlay_mode"]),
                format_func={
                    "all": "All objects",
                    "flagged": "Flagged objects only",
                    "selected": "Selected object only",
                    "none": "Hidden",
                }.get,
            )
            c1, c2, c3 = st.columns(3)
            labels = c1.checkbox("Show labels", p["show_labels"])
            ids = c2.checkbox("Show annotation ids", p["show_ids"])
            zoom = c3.checkbox("Zoom to selection", p["zoom_to_selection"])
            res = st.select_slider(
                "Canvas render width (px)",
                [1000, 1200, 1600, 2000, 2400],
                value=int(p["canvas_resolution"]),
                help="Overlays are drawn at this width and scaled by the browser.",
            )
            if st.form_submit_button("Save inspector settings", type="primary"):
                p.update(
                    overlay_mode=mode, show_labels=labels, show_ids=ids, zoom_to_selection=zoom, canvas_resolution=res
                )
                for k in ("w_insp_mode", "w_insp_labels", "w_insp_ids", "w_insp_zoom"):
                    st.session_state.pop(k, None)
                err = state.save_settings()
                st.error(err) if err else st.success("Inspector settings saved.")

    with tab_a:
        section("LabelGuard")
        dl(
            [
                ("Version", __version__),
                (
                    "Formats",
                    "CVAT for images 1.1 XML, CVAT for video 1.1 XML, COCO instances JSON, "
                    "BDD100K / Scalabel JSON, ZIP archives of these",
                ),
                ("Rules", f"{len(all_rules())} deterministic rules (structural and heuristic)"),
                ("Architecture", "Parsers → normalized model → rule engine → reports / Streamlit UI"),
                ("Network", "Offline. No annotation data leaves this machine."),
                ("Source", "github.com/Sodachan182/labelguard-annotation-qa"),
            ]
        )
