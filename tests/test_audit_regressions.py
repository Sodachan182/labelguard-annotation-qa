"""Regression tests for defects found in the final engineering audit."""

import json
import os
import time

from PIL import Image
from typer.testing import CliRunner

from labelguard.cli import app
from labelguard.parsers import common
from labelguard.parsers.archive import load_directory
from labelguard.parsers.bdd100k import image_size
from labelguard.ui.state import cleanup_stale_sessions, new_workdir
from labelguard.visualization.overlays import OverlayOptions, render_overlay
from tests.conftest import cvat_images

IMG = '<image id="0" name="a.png" width="64" height="32">{}</image>'


def test_long_names_are_truncated_in_the_middle_and_escaped():
    from labelguard.ui.styles import name_html, short_name

    name = "front_camera_" + "x" * 100 + "_frame_000318.png"
    s = short_name(name, 30)
    assert len(s) == 30 and s.startswith("front_camera") and s.endswith("000318.png") and "…" in s
    assert short_name("short.png", 30) == "short.png"
    assert "&lt;b&gt;" in name_html("<b>evil</b>.png") and 'title="&lt;b&gt;' in name_html("<b>evil</b>.png")


def test_decompression_bomb_falls_back_to_blank_canvas(tmp_path, monkeypatch, parse_images):
    Image.new("RGB", (64, 32)).save(tmp_path / "a.png")
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)  # 64*32 > 2*100 -> DecompressionBombError
    ds = parse_images(IMG.format('<box label="car" xtl="1" ytl="1" xbr="20" ybr="20"/>'))
    res = render_overlay(
        ds.images[0], ds.annotations, image_path=str(tmp_path / "a.png"), options=OverlayOptions(target_width=128)
    )
    assert not res.has_pixels
    assert image_size(tmp_path / "a.png") is None


def test_import_workdirs_are_never_reused(tmp_path):
    a = new_workdir(tmp_path, "import")
    (a / "old.xml").write_text("x")
    b = new_workdir(tmp_path, "import")
    assert a != b and not any(b.iterdir())


def test_stale_session_cleanup_only_removes_old_session_folders(tmp_path):
    old = tmp_path / "labelguard-session-old"
    new = tmp_path / "labelguard-session-new"
    other = tmp_path / "unrelated-folder"
    for d in (old, new, other):
        d.mkdir()
    past = time.time() - 3 * 24 * 3600
    os.utime(old, (past, past))
    os.utime(other, (past, past))
    assert cleanup_stale_sessions(tmp_path) == 1
    assert not old.exists() and new.exists() and other.exists()


def test_size_limit_applies_before_json_parsing_in_folders(tmp_path, monkeypatch):
    (tmp_path / "big.json").write_text(json.dumps({"images": [], "annotations": [], "pad": "x" * 200}))
    monkeypatch.setattr(common, "MAX_ANNOTATION_BYTES", 100)
    res = load_directory(tmp_path)
    assert not res.datasets and any("limit" in e for e in res.errors)


def test_report_with_file_out_and_several_datasets_writes_files(tmp_path):
    for n in ("a", "b"):
        d = tmp_path / "in" / n
        d.mkdir(parents=True)
        (d / "annotations.xml").write_bytes(
            cvat_images(IMG.format(f'<box label="car" xtl="1" ytl="1" xbr="{(n == "a" and 1) or 9}" ybr="9"/>'))
        )
    out = tmp_path / "out" / "report.json"
    r = CliRunner().invoke(app, ["report", str(tmp_path / "in"), "--out", str(out)])
    assert r.exit_code == 0, r.output
    written = sorted(p.name for p in out.parent.iterdir())
    assert len(written) == 2 and all(p.startswith("report_") and p.endswith(".json") for p in written)
    assert not out.is_dir()
