"""Small, hand-written annotation records for isolated unit tests.

These fixtures are deliberately tiny artificial records (no images) so the
unit suite runs anywhere; real-data checks live in test_realdata.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from labelguard.parsers.coco_json import parse_coco_json
from labelguard.parsers.cvat_xml import parse_cvat_xml

CVAT_META = """<meta><task><size>2</size><labels>
  <label><name>car</name><attributes><attribute><name>color</name><mutable>False</mutable>
    <input_type>select</input_type><default_value>red</default_value><values>red
blue</values></attribute></attributes></label>
  <label><name>person</name><attributes></attributes></label>
  <label><name>face</name><type>skeleton</type><sublabels>
    <label><name>left_eye</name></label><label><name>right_eye</name></label><label><name>nose</name></label>
  </sublabels></label>
</labels></task></meta>"""


def cvat_images(body: str, meta: str = CVAT_META) -> bytes:
    return f'<?xml version="1.0"?><annotations><version>1.1</version>{meta}{body}</annotations>'.encode()


def cvat_video(tracks: str, size: int = 20, width: int = 640, height: int = 360) -> bytes:
    meta = (
        f"<meta><task><size>{size}</size><start_frame>0</start_frame><stop_frame>{size - 1}</stop_frame>"
        f"<labels><label><name>car</name></label></labels>"
        f"<original_size><width>{width}</width><height>{height}</height></original_size></task></meta>"
    )
    return f"<annotations><version>1.1</version>{meta}{tracks}</annotations>".encode()


@pytest.fixture
def parse_images():
    return lambda body, meta=CVAT_META: parse_cvat_xml(cvat_images(body, meta), "t.xml")


@pytest.fixture
def parse_video():
    return lambda tracks, **kw: parse_cvat_xml(cvat_video(tracks, **kw), "v.xml")


def coco_doc(annotations: list[dict], images: list[dict] | None = None, categories: list[dict] | None = None):
    return {
        "images": images if images is not None else [{"id": 1, "file_name": "a.jpg", "width": 100, "height": 80}],
        "annotations": annotations,
        "categories": categories
        if categories is not None
        else [
            {"id": 1, "name": "car"},
            {"id": 2, "name": "truck"},
            {"id": 3, "name": "person", "keypoints": ["head", "left_hand", "right_hand"]},
        ],
    }


@pytest.fixture
def parse_coco():
    return lambda anns, **kw: parse_coco_json(json.dumps(coco_doc(anns, **kw)).encode(), "c.json")


def bdd_record(name: str, objects: list[dict]) -> dict:
    return {
        "name": name,
        "attributes": {"weather": "clear", "scene": "city street", "timeofday": "daytime"},
        "frames": [{"timestamp": 10000, "objects": objects}],
    }


def box(obj_id: int, cat: str, x1: float, y1: float, x2: float, y2: float, **attrs) -> dict:
    a = {"occluded": False, "truncated": False, "trafficLightColor": "none", **attrs}
    return {"id": obj_id, "category": cat, "attributes": a, "box2d": {"x1": x1, "y1": y1, "x2": x2, "y2": y2}}


@pytest.fixture
def data_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "bdd100k"
