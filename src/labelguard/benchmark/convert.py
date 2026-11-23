"""Convert BDD100K detection labels to COCO and CVAT for images 1.1.

COCO conversion follows the official BDD100K / Scalabel rule
(``scalabel.label.transforms.box2d_to_bbox``)::

    bbox = [x1, y1, x2 - x1 + 1, y2 - y1 + 1]

CVAT boxes are continuous corners, so the equivalent CVAT box is
``xtl = x1, ytl = y1, xbr = x2 + 1, ybr = y2 + 1``. Both conversions describe
the same pixel extent; :mod:`labelguard.benchmark.compare` verifies that.

Every skipped object is counted in the returned :class:`ConversionReport`.
"""

from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from labelguard.parsers.bdd100k import ONTOLOGIES, _objects, _records


@dataclass
class ConversionReport:
    images: int = 0
    converted: int = 0
    skipped: Counter = field(default_factory=Counter)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "images": self.images,
            "converted_boxes": self.converted,
            "skipped": dict(self.skipped),
            "errors": self.errors,
        }


def _box(obj: dict) -> tuple[float, float, float, float] | None:
    b = obj.get("box2d")
    if not isinstance(b, dict):
        return None
    try:
        vals = tuple(float(b[k]) for k in ("x1", "y1", "x2", "y2"))
    except (KeyError, TypeError, ValueError):
        return None
    return vals if all(math.isfinite(v) for v in vals) else None


def load_records(path: Path) -> list[dict]:
    """Records from a combined label file or a folder of per-image files."""
    if path.is_dir():
        recs = []
        for p in sorted(path.glob("*.json")):
            recs.extend(_records(json.loads(p.read_text(encoding="utf-8"))))
        return recs
    return _records(json.loads(path.read_text(encoding="utf-8")))


def to_coco(
    records: list[dict], ontology: str = "bdd100k_labels_2018", size: tuple[int, int] = (1280, 720)
) -> tuple[dict, ConversionReport]:
    rep = ConversionReport()
    cats = ONTOLOGIES[ontology]
    cat_id = {c: i + 1 for i, c in enumerate(cats)}
    images, anns = [], []
    ann_id = 1
    for img_id, rec in enumerate(records, start=1):
        rep.images += 1
        images.append({"id": img_id, "file_name": rec.get("name", ""), "width": size[0], "height": size[1]})
        for obj in _objects(rec):
            if "box2d" not in obj:
                rep.skipped[f"non-detection ({str(obj.get('category', '?')).split('/')[0]})"] += 1
                continue
            box = _box(obj)
            if box is None:
                rep.skipped["invalid box2d"] += 1
                rep.errors.append(f"{rec.get('name')}: object {obj.get('id')} has an invalid box2d")
                continue
            if obj.get("category") not in cat_id:
                rep.skipped[f"category not in ontology ({obj.get('category')})"] += 1
                continue
            x1, y1, x2, y2 = box
            w, h = x2 - x1 + 1, y2 - y1 + 1
            attrs = obj.get("attributes") or {}
            anns.append(
                {
                    "id": ann_id,
                    "image_id": img_id,
                    "category_id": cat_id[obj["category"]],
                    "bbox": [x1, y1, w, h],
                    "area": max(w, 0) * max(h, 0),
                    "iscrowd": 0,
                    "segmentation": [],
                    "attributes": {
                        "bdd100k_id": obj.get("id"),
                        "occluded": bool(attrs.get("occluded", False)),
                        "truncated": bool(attrs.get("truncated", False)),
                        "trafficLightColor": attrs.get("trafficLightColor", "none"),
                    },
                }
            )
            ann_id += 1
            rep.converted += 1
    coco = {
        "info": {"description": "BDD100K subset converted by LabelGuard (Scalabel box2d_to_bbox convention)"},
        "images": images,
        "annotations": anns,
        "categories": [{"id": i, "name": c, "supercategory": "none"} for c, i in cat_id.items()],
    }
    return coco, rep


def to_cvat_xml(
    records: list[dict], ontology: str = "bdd100k_labels_2018", size: tuple[int, int] = (1280, 720)
) -> tuple[bytes, ConversionReport]:
    rep = ConversionReport()
    cats = ONTOLOGIES[ontology]
    root = ET.Element("annotations")
    ET.SubElement(root, "version").text = "1.1"
    task = ET.SubElement(ET.SubElement(root, "meta"), "task")
    ET.SubElement(task, "name").text = "BDD100K subset"
    ET.SubElement(task, "size").text = str(len(records))
    labels = ET.SubElement(task, "labels")
    for c in cats:
        lab = ET.SubElement(labels, "label")
        ET.SubElement(lab, "name").text = c
        ET.SubElement(lab, "type").text = "rectangle"
        attrs = ET.SubElement(lab, "attributes")
        for name, itype, values in (
            ("truncated", "checkbox", "false"),
            ("trafficLightColor", "select", "none\nred\ngreen\nyellow"),
        ):
            a = ET.SubElement(attrs, "attribute")
            ET.SubElement(a, "name").text = name
            ET.SubElement(a, "mutable").text = "False"
            ET.SubElement(a, "input_type").text = itype
            ET.SubElement(a, "default_value").text = values.split("\n")[0]
            ET.SubElement(a, "values").text = values
    for idx, rec in enumerate(records):
        rep.images += 1
        img = ET.SubElement(
            root, "image", id=str(idx), name=rec.get("name", ""), width=str(size[0]), height=str(size[1])
        )
        for obj in _objects(rec):
            if "box2d" not in obj:
                rep.skipped[f"non-detection ({str(obj.get('category', '?')).split('/')[0]})"] += 1
                continue
            box = _box(obj)
            if box is None or obj.get("category") not in cats:
                rep.skipped["invalid box2d or category"] += 1
                continue
            x1, y1, x2, y2 = box
            attrs = obj.get("attributes") or {}
            el = ET.SubElement(
                img,
                "box",
                label=obj["category"],
                source="manual",
                occluded="1" if attrs.get("occluded") else "0",
                xtl=f"{x1:.4f}",
                ytl=f"{y1:.4f}",
                xbr=f"{x2 + 1:.4f}",
                ybr=f"{y2 + 1:.4f}",
                z_order="0",
            )
            ET.SubElement(el, "attribute", name="truncated").text = "true" if attrs.get("truncated") else "false"
            ET.SubElement(el, "attribute", name="trafficLightColor").text = str(attrs.get("trafficLightColor", "none"))
            rep.converted += 1
    ET.indent(root, space="  ")
    return b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="utf-8"), rep
