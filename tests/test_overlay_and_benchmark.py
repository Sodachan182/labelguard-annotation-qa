"""Overlay geometry, BDD100K conversion/corruption/evaluation, and the app shell."""

import pytest
from PIL import Image

from labelguard.benchmark.compare import compare_datasets
from labelguard.benchmark.convert import to_coco, to_cvat_xml
from labelguard.benchmark.corrupt import ERROR_TYPES, corrupt
from labelguard.evaluation import evaluate_findings
from labelguard.parsers.bdd100k import dataset_from_records
from labelguard.parsers.coco_json import parse_coco_json
from labelguard.parsers.cvat_xml import parse_cvat_xml
from labelguard.validation import validate
from labelguard.visualization.overlays import OverlayOptions, ViewTransform, compute_window, render_overlay
from tests.conftest import bdd_record, box

IMG = '<image id="0" name="a.jpg" width="200" height="100">{}</image>'


def test_view_transform_round_trip():
    tf = ViewTransform(-10, -20, 190, 80, scale=4.0)
    assert tf.to_canvas(-10, -20) == (0, 0)
    assert tf.to_canvas(40, 5) == (200, 100)
    assert tf.to_source(*tf.to_canvas(123.5, 45.25)) == pytest.approx((123.5, 45.25))
    assert tf.size == (800, 400)


def test_window_extends_for_out_of_bounds_and_zoom(parse_images):
    ds = parse_images(
        IMG.format(
            '<box label="car" xtl="150" ytl="10" xbr="260" ybr="40"/>'
            '<box label="car" xtl="10" ytl="10" xbr="12" ybr="12"/>'
        )
    )
    w = compute_window(200, 100, ds.annotations, None, zoom=False)
    assert w[0] == 0 and w[2] > 260  # widened to show the defect, with padding
    tiny = ds.annotations[1]
    z = compute_window(200, 100, ds.annotations, tiny, zoom=True)
    assert (z[2] - z[0]) >= 200 / 5 - 1e-9  # magnification is capped
    assert z[0] < 11 < z[2]


def test_overlay_draws_at_exact_coordinates(tmp_path, parse_images):
    Image.new("RGB", (200, 100), (0, 0, 0)).save(tmp_path / "a.png")
    ds = parse_images(IMG.format('<box label="car" xtl="50" ytl="20" xbr="150" ybr="80"/>'))
    res = render_overlay(
        ds.images[0],
        ds.annotations,
        image_path=str(tmp_path / "a.png"),
        options=OverlayOptions(target_width=400, show_labels=False),
    )
    assert res.has_pixels and res.image.size == (400, 200) and res.transform.scale == 2.0
    px = res.image.load()
    assert px[100, 100] != (0, 0, 0)  # left edge of the box at x=50 → 100
    assert px[200, 100] == (0, 0, 0)  # box interior untouched
    assert px[90, 100] == (0, 0, 0)  # outside the box


def test_overlay_without_image_is_a_blank_canvas(parse_images):
    ds = parse_images(IMG.format('<box label="car" xtl="50" ytl="20" xbr="150" ybr="80"/>'))
    res = render_overlay(
        ds.images[0], ds.annotations, selected_id=ds.annotations[0].id, options=OverlayOptions(target_width=400)
    )
    assert not res.has_pixels and res.image.size == (400, 200)


# ------------------------------------------------------- BDD100K benchmark

RECORDS = [
    bdd_record(
        f"img{i}",
        [box(j, "car", 100 + 150 * j, 300, 199 + 150 * j, 379) for j in range(5)]
        + [{"id": 99, "category": "area/drivable", "poly2d": []}],
    )
    for i in range(12)
]


def test_conversions_round_trip_exactly():
    ref = dataset_from_records(RECORDS, "ref")
    coco, rep = to_coco(RECORDS)
    assert rep.converted == 60 and rep.skipped == {"non-detection (area)": 12}
    assert coco["annotations"][0]["bbox"] == [100, 300, 100, 80]  # x2 - x1 + 1
    coco_ds = parse_coco_json(__import__("json").dumps(coco).encode())
    cmp = compare_datasets(ref, coco_ds)
    assert cmp.identical and cmp.matched == 60 and cmp.max_abs_delta_px == 0
    xml, _ = to_cvat_xml(RECORDS)
    cvat_cmp = compare_datasets(ref, parse_cvat_xml(xml))
    assert cvat_cmp.identical and cvat_cmp.max_abs_delta_px < 1e-3


def test_compare_reports_differences():
    ref = dataset_from_records(RECORDS[:2], "ref")
    changed = [bdd_record("img0", [box(0, "car", 105, 300, 199, 379)]), bdd_record("img1", [])]
    cmp = compare_datasets(ref, dataset_from_records(changed, "c"))
    assert not cmp.identical and cmp.coordinate_mismatches and len(cmp.missing_boxes) == 9


def test_corruption_is_deterministic_and_detected(tmp_path):
    a, man_a = corrupt(RECORDS, seed=3, per_type=1)
    b, man_b = corrupt(RECORDS, seed=3, per_type=1)
    assert man_a == man_b and a == b
    assert RECORDS[0]["frames"][0]["objects"][0]["box2d"]["x1"] == 100  # originals untouched
    assert {m["error_type"] for m in man_a} == {e[0] for e in ERROR_TYPES}
    # INT009 (image file not supplied) only applies when images are supplied, as in the real benchmark.
    for r in RECORDS:
        Image.new("RGB", (1280, 720)).save(tmp_path / f"{r['name']}.jpg")
    base = validate(dataset_from_records(RECORDS, "o", image_dir=tmp_path))
    bad = validate(dataset_from_records(a, "c", image_dir=tmp_path))
    ev = evaluate_findings([(m["expected_rule"], m["target"]) for m in man_a], bad.issues, base.issues)
    assert ev["overall"]["fn"] == 0 and ev["overall"]["tp"] == len(man_a)


def test_evaluation_metrics_and_pre_existing():
    base = validate(dataset_from_records([bdd_record("x", [box(0, "car", 1, 1, 4, 3)])], "o"))  # tiny box
    pre = {(i.rule_id, i.annotation_id) for i in base.issues}
    ev = evaluate_findings([("BOX001", "x:9")], base.issues, base.issues)
    assert ev["pre_existing_excluded"] == len(pre) and ev["overall"] == {
        "tp": 0,
        "fp": 0,
        "fn": 1,
        "precision": None,
        "recall": 0.0,
        "f1": None,
    }
