"""Headless Streamlit smoke tests (no browser): every page renders without exceptions,
both empty and with a loaded dataset, and selection state drives the Inspector."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

PAGES = ["overview", "datasets", "issues", "inspector", "reports", "settings"]


def page_script(page: str, xml_path: str | None, settings: str, select_first: bool = False):
    from pathlib import Path

    import streamlit as st

    from labelguard.ui import state

    state.SETTINGS_FILE = Path(settings)
    state.DATA_ROOT = Path(settings).parent / "data"
    state.init()
    if xml_path and not state.entries():
        state.add_from_path(Path(xml_path), "test")
        if select_first:
            state.select_issue(state.active().report.issues[0])
    module = __import__(f"labelguard.ui.pages.{page}", fromlist=["render"])
    st.session_state["rendered"] = page
    module.render()


@pytest.fixture
def xml(tmp_path) -> Path:
    from tests.conftest import cvat_images

    p = tmp_path / "annotations.xml"
    p.write_bytes(
        cvat_images(
            '<image id="0" name="a.jpg" width="100" height="80">'
            '<box label="car" xtl="10" ytl="10" xbr="10" ybr="30"/>'
            '<box label="car" xtl="20" ytl="20" xbr="60" ybr="50"/></image>'
        )
    )
    return p


@pytest.mark.parametrize("page", PAGES)
def test_empty_page_renders(page, tmp_path):
    at = AppTest.from_function(page_script, args=(page, None, str(tmp_path / "s.json")), default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    assert at.session_state["rendered"] == page


@pytest.mark.parametrize("page", PAGES)
def test_loaded_page_renders(page, xml, tmp_path):
    at = AppTest.from_function(page_script, args=(page, str(xml), str(tmp_path / "s.json")), default_timeout=60)
    at.run()
    assert not at.exception, at.exception


def test_inspector_shows_selected_finding(xml, tmp_path):
    at = AppTest.from_function(
        page_script, args=("inspector", str(xml), str(tmp_path / "s.json"), True), default_timeout=60
    )
    at.run()
    assert not at.exception
    assert at.session_state["lg_selected_issue"].startswith("LG-")
    assert at.session_state["lg_selected_annotation"] == "0:1"
    html = " ".join(str(h.proto) for h in at.get("html"))
    assert "Box has zero area" in html
