import json
import math

import pytest

from labelguard.models import GeometryType, SourceFormat
from labelguard.parsers import ParseError, parse_bytes, parse_cvat_xml
from labelguard.parsers.bdd100k import dataset_from_records, parse_bdd100k
from tests.conftest import bdd_record, box

# ---------------------------------------------------------------- CVAT images


def test_cvat_images_shapes_and_metadata(parse_images):
    ds = parse_images(
        '<image id="0" name="a.jpg" width="100" height="80">'
        '<box label="car" xtl="1" ytl="2" xbr="30" ybr="40" occluded="1"><attribute name="color">blue</attribute></box>'
        '<polygon label="person" points="1,1;10,1;10,10"/>'
        '<points label="person" points="5,5;6,6"/>'
        '<polyline label="person" points="0,0;5,5"/>'
        '<skeleton label="face"><points label="left_eye" points="10,10" outside="0" occluded="0"/>'
        '<points label="nose" points="12,14" outside="0" occluded="1"/></skeleton>'
        '<mask label="car" rle="1,2,3" left="0" top="0" width="2" height="2"/>'
        '<tag label="car"/></image>'
    )
    assert ds.source_format == SourceFormat.CVAT_IMAGES
    kinds = [a.geometry_type for a in ds.annotations]
    assert kinds == [
        GeometryType.BBOX,
        GeometryType.POLYGON,
        GeometryType.POINTS,
        GeometryType.POLYLINE,
        GeometryType.KEYPOINTS,
        GeometryType.UNSUPPORTED,
    ]
    car = ds.annotations[0]
    assert car.bbox == [1, 2, 30, 40] and car.bbox_source == [1, 2, 30, 40]
    assert car.attributes == {"color": "blue"} and car.occluded
    assert car.id == "0:1"
    sk = ds.annotations[4]
    assert sk.keypoint_visibility == [2, 1] and sk.raw["keypoint_names"] == ["left_eye", "nose"]
    assert [c.name for c in ds.categories] == ["car", "person", "face"]
    assert ds.categories[2].keypoint_names == ["left_eye", "right_eye", "nose"]
    assert any("tag" in w for w in ds.parse_warnings)


def test_cvat_invalid_numbers_are_kept_not_dropped(parse_images):
    ds = parse_images(
        '<image id="0" name="a.jpg" width="100" height="80">'
        '<box label="car" xtl="1" ytl="abc" xbr="30" ybr="40"/></image>'
    )
    a = ds.annotations[0]
    assert math.isnan(a.bbox[1]) and any("not a number" in e for e in a.parse_errors)


def test_cvat_video_tracks(parse_video):
    ds = parse_video(
        '<track id="3" label="car" source="manual">'
        '<box frame="0" keyframe="1" outside="0" occluded="0" xtl="1" ytl="1" xbr="20" ybr="20"/>'
        '<box frame="5" keyframe="1" outside="1" occluded="0" xtl="1" ytl="1" xbr="20" ybr="20"/>'
        "</track>",
        size=10,
    )
    assert ds.is_video and ds.frame_range == (0, 9) and len(ds.images) == 10
    a, b = ds.annotations
    assert (a.frame, a.track_id, a.keyframe, a.outside) == (0, "3", True, False)
    assert b.outside and b.image_id == "frame_000005"


def test_xml_entity_expansion_is_rejected():
    bomb = (
        b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;">]>'
        b"<annotations>&lol2;</annotations>"
    )
    with pytest.raises(ParseError, match="unsafe XML"):
        parse_cvat_xml(bomb)


def test_external_entity_is_rejected():
    xxe = b'<?xml version="1.0"?><!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><annotations>&x;</annotations>'
    with pytest.raises(ParseError):
        parse_cvat_xml(xxe)


def test_not_cvat_xml():
    with pytest.raises(ParseError, match="expected CVAT"):
        parse_cvat_xml(b"<root/>")
    with pytest.raises(ParseError, match="well-formed"):
        parse_cvat_xml(b"<annotations>")


# ---------------------------------------------------------------------- COCO


def test_coco_bbox_is_xywh(parse_coco):
    ds = parse_coco([{"id": 7, "image_id": 1, "category_id": 1, "bbox": [10, 20, 30, 40]}])
    a = ds.annotations[0]
    assert a.bbox == [10, 20, 40, 60] and a.bbox_source == [10, 20, 30, 40]
    assert a.category == "car" and a.geometry_type == GeometryType.BBOX


def test_coco_duplicates_segmentation_keypoints(parse_coco):
    ds = parse_coco(
        [
            {"id": 1, "image_id": 1, "category_id": 1, "bbox": [0, 0, 5, 5], "segmentation": [[0, 0, 5, 0, 5, 5, 0]]},
            {"id": 1, "image_id": 1, "category_id": 3, "bbox": [0, 0, 5, 5], "keypoints": [1, 1, 2, 2, 2, 0, 3, 3, 1]},
            {
                "id": 2,
                "image_id": 1,
                "category_id": 1,
                "bbox": [0, 0, 5, 5],
                "segmentation": {"counts": "x", "size": [1, 1]},
            },
        ]
    )
    a, b, c = ds.annotations
    assert a.geometry_type == GeometryType.POLYGON and any("odd number" in e for e in a.parse_errors)
    assert b.id == "1~2" and b.raw["source_id"] == "1"
    assert b.geometry_type == GeometryType.KEYPOINTS and b.keypoint_visibility == [2, 0, 1]
    assert c.raw.get("segmentation_rle") is True


def test_coco_missing_fields(parse_coco):
    ds = parse_coco([{"id": 3, "image_id": 1, "bbox": [0, 0, 1, 1]}])
    assert "missing 'category_id'" in ds.annotations[0].parse_errors


def test_detect_json_kinds():
    coco = json.dumps({"images": [], "annotations": []}).encode()
    assert parse_bytes(coco, "c.json").source_format == SourceFormat.COCO
    bdd = json.dumps([bdd_record("x.jpg", [box(0, "car", 1, 1, 9, 9)])]).encode()
    assert parse_bytes(bdd, "b.json").source_format == SourceFormat.BDD100K
    with pytest.raises(ParseError):
        parse_bytes(b'{"hello": 1}', "x.json")
    with pytest.raises(ParseError):
        parse_bytes(b"PK\x03\x04", "x.bin")


# ------------------------------------------------------------------- BDD100K


def test_bdd_inclusive_pixel_convention():
    ds = dataset_from_records([bdd_record("img.jpg", [box(0, "car", 10, 20, 29, 59)])], "b")
    a = ds.annotations[0]
    assert a.bbox_source == [10, 20, 29, 59]
    assert a.bbox == [10, 20, 30, 60]  # width = x2 - x1 + 1 = 20
    assert a.attributes["occluded"] == "false"


def test_bdd_ids_are_scoped_per_image_and_poly2d_counted():
    recs = [
        bdd_record("a", [box(0, "car", 1, 1, 9, 9), {"id": 1, "category": "lane/road curb", "poly2d": []}]),
        bdd_record("b", [box(0, "car", 1, 1, 9, 9)]),
    ]
    ds = dataset_from_records(recs, "b")
    assert [a.id for a in ds.annotations] == ["a:0", "b:0"]
    assert ds.metadata["skipped_objects"] == {"poly2d:lane": 1}
    assert any("not validated" in w for w in ds.parse_warnings)


def test_bdd_list_format_and_ontology_detection():
    det20 = [
        {
            "name": "x.jpg",
            "labels": [{"id": "5", "category": "pedestrian", "box2d": {"x1": 1, "y1": 1, "x2": 5, "y2": 9}}],
        }
    ]
    ds = parse_bdd100k(json.dumps(det20).encode())
    assert ds.metadata["ontology"] == "det_20"
    assert ds.annotations[0].category_id is not None


def test_bdd_image_lookup_adds_extension_and_reads_size(tmp_path):
    from PIL import Image

    Image.new("RGB", (64, 32)).save(tmp_path / "abc.jpg")
    ds = dataset_from_records([bdd_record("abc", [box(0, "car", 1, 1, 9, 9)])], "b", image_dir=tmp_path)
    img = ds.images[0]
    assert (img.width, img.height) == (64, 32) and img.raw["size_source"] == "image file"
    ds2 = dataset_from_records([bdd_record("missing", [])], "b")
    assert (ds2.images[0].width, ds2.images[0].height) == (1280, 720)
    assert any("assumed" in w for w in ds2.parse_warnings)
