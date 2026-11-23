"""Application shell: page config, theme, navigation and the dataset switcher."""

from __future__ import annotations

import streamlit as st

from labelguard.ui import state
from labelguard.ui.styles import inject_css
from labelguard.ui.theme import theme_type

PAGES: dict[str, st.Page] = {}


def _brand() -> None:
    root = state.PROJECT_ROOT / "assets" / "brand"
    logo = root / ("logo-light.svg" if theme_type() == "light" else "logo-dark.svg")
    st.logo(str(logo), size="large", icon_image=str(root / "icon.svg"))


def _dataset_switcher() -> None:
    entries = state.entries()
    with st.sidebar:
        if not entries:
            st.caption("No dataset loaded")
            return
        ids = list(entries)
        ss = st.session_state
        # The app state is the source of truth. If the widget differs from what was
        # rendered last time, the user picked it; otherwise any difference comes from the
        # app (a new import, a loaded sample) and the widget is updated to match.
        picked = ss.get("w_active_dataset")
        if picked in ids and picked != ss.get("lg_switcher_rendered"):
            state.set_active(picked)
        current = state.active()
        ss["w_active_dataset"] = ss["lg_switcher_rendered"] = current.id if current else ids[0]
        names = [entries[i].dataset.name for i in ids]

        def label(i: str) -> str:
            name = entries[i].dataset.name
            return f"{name} · {i[-8:]}" if names.count(name) > 1 else name

        st.selectbox("Active dataset", ids, format_func=label, key="w_active_dataset")
        e = entries[ss["w_active_dataset"]]
        n = len(e.report.issues) if e.report else 0
        st.caption(f"{e.dataset.source_format.label} · {len(e.dataset.images)} images · {n} findings")


def main() -> None:
    st.set_page_config(
        page_title="LabelGuard",
        page_icon=str(state.PROJECT_ROOT / "assets" / "brand" / "icon.svg"),
        layout="wide",
        initial_sidebar_state="auto",  # expanded on desktop, collapsed on phones
    )
    state.init()
    inject_css()
    _brand()

    from labelguard.ui.pages import datasets, inspector, issues, overview, reports, settings

    PAGES.update(
        overview=st.Page(
            overview.render, title="Overview", icon=":material/space_dashboard:", url_path="overview", default=True
        ),
        datasets=st.Page(datasets.render, title="Datasets", icon=":material/folder_open:", url_path="datasets"),
        issues=st.Page(issues.render, title="Issues", icon=":material/rule:", url_path="issues"),
        inspector=st.Page(
            inspector.render, title="Inspector", icon=":material/center_focus_strong:", url_path="inspector"
        ),
        reports=st.Page(reports.render, title="Reports", icon=":material/description:", url_path="reports"),
        settings=st.Page(settings.render, title="Settings", icon=":material/tune:", url_path="settings"),
    )
    nav = st.navigation(list(PAGES.values()), position="sidebar")
    _dataset_switcher()
    nav.run()


def go(page: str) -> None:
    st.switch_page(PAGES[page])
