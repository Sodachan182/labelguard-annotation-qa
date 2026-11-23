"""Every rule fires on a minimal defect and stays quiet on clean data."""

from collections import Counter

import pytest

from labelguard.config import PROFILES, ValidationConfig
from labelguard.models import IssueKind, Severity
from labelguard.parsers.bdd100k import dataset_from_records
from labelguard.validation import all_rules, validate
from labelguard.validation.engine import active_rules
from tests.conftest import bdd_record, box

IMG = '<image id="0" name="a.jpg" width="100" height="80">{}</image>'


def rules_of(ds, cfg=None):
    return Counter(i.rule_id for i in validate(ds, cfg).issues)


def test_registry_has_stable_unique_ids():
    ids = [r.id for r in all_rules()]
    assert len(ids) == len(set(ids)) >= 30
    for r in all_rules():
        assert r.kind in IssueKind and r.severity in Severity and r.description


def test_clean_cvat_dataset_has_no_findings(parse_images):
    ds = parse_images(
        IMG.format(
            '<box label="car" xtl="10" ytl="10" xbr="40" ybr="30"><attribute name="color">red</attribute></box>'
            '<box label="person" xtl="60" ytl="20" xbr="75" ybr="70"/>'
            '<polygon label="person" points="50,5;70,5;70,15;50,15"/>'
        )
    )
    assert rules_of(ds) == Counter()


@pytest.mark.parametrize(
    "shape, rule",
    [
        ('<box label="car" xtl="10" ytl="10" xbr="10" ybr="30"/>', "BOX001"),
        ('<box label="car" xtl="30" ytl="10" xbr="10" ybr="30"/>', "BOX002"),
        ('<box label="car" xtl="80" ytl="10" xbr="130" ybr="30"/>', "BOX003"),
        ('<box label="car" xtl="10" ytl="10" xbr="14" ybr="14"/>', "BOX004"),
        ('<box label="car" xtl="0" ytl="10" xbr="99" ybr="15"/>', "BOX005"),
        ('<box label="truck" xtl="10" ytl="10" xbr="40" ybr="30"/>', "INT004"),
        ('<box label="car" xtl="10" ytl="1O" xbr="40" ybr="30"/>', "INT002"),
        (
            '<box label="car" xtl="10" ytl="10" xbr="40" ybr="30"><attribute name="color">green</attribute></box>',
            "INT007",
        ),
        ('<box label="car" xtl="10" ytl="10" xbr="40" ybr="30"><attribute name="speed">5</attribute></box>', "INT007"),
        ('<polygon label="person" points="1,1;5,5;5,5"/>', "POL001"),
        ('<polygon label="person" points="0,0;10,10;10,0;0,10"/>', "POL002"),
        ('<polygon label="person" points="0,0;5,5;10,10"/>', "POL003"),
        ('<polygon label="person" points="0,0;20,0;20,0;20,20;0,20"/>', "POL004"),
        ('<polygon label="person" points="0,0;120,0;120,20;0,20"/>', "POL005"),
        ('<polygon label="person" points="0,0;4,0;4,4;0,4"/>', "POL006"),
        ('<polygon label="person" points="0,0;10;10,10"/>', "POL007"),
        ('<points label="person" points="50,50;150,50"/>', "KPT001"),
        ('<ellipse label="car" cx="5" cy="5" rx="2" ry="3"/>', "INT008"),
    ],
)
def test_single_defect_triggers_rule(parse_images, shape, rule):
    found = rules_of(parse_images(IMG.format(shape)))
    assert found[rule] >= 1, found


def test_duplicate_and_conflict(parse_images):
    ds = parse_images(
        IMG.format(
            '<box label="car" xtl="10" ytl="10" xbr="40" ybr="30"/>'
            '<box label="car" xtl="10.5" ytl="10" xbr="40" ybr="30"/>'
            '<box label="person" xtl="50" ytl="10" xbr="80" ybr="40"/>'
            '<box label="car" xtl="50" ytl="10" xbr="80.5" ybr="40"/>'
        )
    )
    issues = validate(ds).issues
    dup = [i for i in issues if i.rule_id == "BOX006"]
    conf = [i for i in issues if i.rule_id == "BOX007"]
    assert len(dup) == 1 and dup[0].annotation_id == "0:2" and dup[0].evidence["other_annotation"] == "0:1"
    assert len(conf) == 1 and conf[0].kind == IssueKind.HEURISTIC


def test_allowed_overlap_pairs_suppress_conflicts():
    recs = [bdd_record("r", [box(0, "rider", 10, 10, 50, 90), box(1, "bike", 10, 11, 50, 90)])]
    ds = dataset_from_records(recs, "b")
    assert rules_of(ds)["BOX007"] == 1
    assert rules_of(ds, ValidationConfig.for_profile("bdd100k_detection"))["BOX007"] == 0


def test_heuristics_skip_structurally_broken_boxes(parse_images):
    found = rules_of(parse_images(IMG.format('<box label="car" xtl="10" ytl="10" xbr="10" ybr="30"/>')))
    assert found == Counter({"BOX001": 1})  # no tiny / aspect cascade


def test_image_level_rules(parse_images):
    ds = parse_images(
        '<image id="0" name="a.jpg" width="0" height="80"/><image id="0" name="b.jpg" width="100" height="80"/>'
    )
    found = rules_of(ds)
    assert found["INT005"] == 1 and found["INT003"] == 1


def test_coco_reference_rules(parse_coco):
    ds = parse_coco(
        [
            {"id": 1, "image_id": 99, "category_id": 1, "bbox": [0, 0, 5, 5]},
            {"id": 2, "image_id": 1, "category_id": 42, "bbox": [0, 0, 10, 10]},
            {"id": 3, "image_id": 1, "bbox": [20, 20, 10, 10]},
        ]
    )
    found = rules_of(ds)
    assert found["INT006"] == 1 and found["INT004"] == 1 and found["INT001"] == 1


def test_keypoint_rules(parse_coco):
    ds = parse_coco(
        [
            {"id": 1, "image_id": 1, "category_id": 3, "bbox": [10, 10, 20, 20], "keypoints": [15, 15, 2, 20, 20, 2]},
            {
                "id": 2,
                "image_id": 1,
                "category_id": 3,
                "bbox": [10, 10, 20, 20],
                "keypoints": [15, 15, 2, 20, 20, 2, 25, 25],
            },
            {
                "id": 3,
                "image_id": 1,
                "category_id": 3,
                "bbox": [10, 10, 20, 20],
                "keypoints": [15, 15, 2, 90, 70, 2, 20, 20, 1],
            },
            {
                "id": 4,
                "image_id": 1,
                "category_id": 3,
                "bbox": [60, 10, 20, 20],
                "keypoints": [65, 15, 2, 70, 15, 2, 120, 15, 2],
            },
        ]
    )
    issues = validate(ds).issues
    by = {(i.rule_id, i.annotation_id) for i in issues}
    assert ("KPT003", "1") in by  # 2 of 3 keypoints
    assert ("KPT002", "2") in by and ("KPT003", "2") not in by  # no cascade
    assert ("KPT004", "3") in by  # far outside its own box
    assert ("KPT001", "4") in by


def test_keypoint_order_rule():
    cfg = ValidationConfig(keypoints={"order_rules": [("right_hand", "left_hand")]})
    import json

    from labelguard.parsers.coco_json import parse_coco_json
    from tests.conftest import coco_doc

    doc = coco_doc(
        [
            {
                "id": 1,
                "image_id": 1,
                "category_id": 3,
                "bbox": [10, 10, 40, 40],
                "keypoints": [30, 12, 2, 15, 30, 2, 45, 30, 2],
            }
        ]
    )
    ds = parse_coco_json(json.dumps(doc).encode())
    assert any(i.rule_id == "KPT004" for i in validate(ds, cfg).issues)


# -------------------------------------------------------------------- tracks


def _track(tid, shapes, label="car"):
    rows = "".join(
        f'<box frame="{f}" keyframe="{k}" outside="{o}" occluded="0" '
        f'xtl="{x}" ytl="100" xbr="{x + w}" ybr="{100 + h}"/>'
        for f, x, w, h, k, o in shapes
    )
    return f'<track id="{tid}" label="{label}" source="manual">{rows}</track>'


def test_smooth_track_and_sparse_keyframes_are_clean(parse_video):
    smooth = [(f, 10 + 3 * f, 60, 30, int(f % 5 == 0), 0) for f in range(12)]
    sparse = [(f, 300 + f, 50, 30, 1, 0) for f in (0, 10, 19)]
    ds = parse_video(_track(0, smooth) + _track(1, sparse))
    assert rules_of(ds, ValidationConfig.for_profile("video_tracking")) == Counter()


def test_track_anomalies(parse_video):
    jump = [(0, 10, 60, 30, 1, 0), (1, 13, 60, 30, 0, 0), (2, 200, 60, 30, 1, 0)]
    scale = [(0, 300, 40, 20, 1, 0), (1, 302, 40, 20, 0, 0), (2, 290, 80, 40, 1, 0)]
    reenter = [(0, 400, 40, 20, 1, 0), (3, 400, 40, 20, 1, 1), (6, 410, 40, 20, 0, 0)]
    out_of_range = [(0, 500, 40, 20, 1, 0), (25, 500, 40, 20, 1, 0)]
    never = [(4, 10, 10, 10, 1, 1)]
    ds = parse_video(
        _track(0, jump) + _track(1, scale) + _track(2, reenter) + _track(3, out_of_range) + _track(4, never)
    )
    issues = validate(ds).issues
    by = {(i.rule_id, i.annotation_id) for i in issues}
    assert ("TRK004", "t0:3") in by
    assert ("TRK005", "t1:3") in by
    assert ("TRK003", "t2:3") in by
    assert ("TRK001", "t3:2") in by
    assert any(i.rule_id == "TRK002" and i.track_id == "4" for i in issues)


def test_gap_policy(parse_video):
    ds = parse_video(_track(0, [(0, 10, 40, 20, 1, 0), (15, 40, 40, 20, 1, 0)]))
    assert rules_of(ds)["TRK006"] == 0
    cfg = ValidationConfig(tracks={"gap_policy": "explicit", "max_gap": 10})
    assert rules_of(ds, cfg)["TRK006"] == 1


# -------------------------------------------------------------------- config


def test_profiles_build_and_validate():
    for pid in PROFILES:
        cfg = ValidationConfig.for_profile(pid)
        assert cfg.profile == pid and active_rules(cfg)
    with pytest.raises(ValueError):
        ValidationConfig(profile="nope")
    with pytest.raises(ValueError):
        ValidationConfig(boxes={"duplicate_iou": 1.5})


def test_disable_and_override(parse_images):
    ds = parse_images(IMG.format('<box label="car" xtl="10" ytl="10" xbr="14" ybr="14"/>'))
    assert rules_of(ds, ValidationConfig(disabled_rules=["BOX004"]))["BOX004"] == 0
    report = validate(ds, ValidationConfig(severity_overrides={"BOX004": "info"}))
    assert report.issues[0].severity == Severity.INFO


def test_issue_ids_are_deterministic(parse_images):
    ds = parse_images(IMG.format('<box label="car" xtl="10" ytl="10" xbr="10" ybr="30"/>'))
    assert validate(ds).issues[0].issue_id == validate(ds).issues[0].issue_id
