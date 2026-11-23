"""COCO instances / person-keypoints JSON parser.

COCO boxes are ``[x, y, width, height]`` with the origin at the top-left corner.
They are converted to corner form for validation, and the original list is kept
in ``Annotation.bbox_source`` for reports.
"""

from __future__ import annotations

import json
import math
from typing import Any

from labelguard.geometry.boxes import coco_to_xyxy
from labelguard.models import (
    Annotation,
    Category,
    Dataset,
    GeometryType,
    ImageRecord,
    SourceFormat,
)
from labelguard.parsers.common import (
    IdAllocator,
    ParseError,
    check_size,
    dataset_id_for,
    decode_text,
    to_float,
)


def parse_coco_json(data: bytes, name: str = "instances.json") -> Dataset:
    check_size(data, name)
    try:
        doc = json.loads(decode_text(data))
    except json.JSONDecodeError as exc:
        raise ParseError(f"{name}: not valid JSON ({exc.msg} at line {exc.lineno}).") from exc
    if not isinstance(doc, dict) or not any(k in doc for k in ("images", "annotations")):
        raise ParseError(f"{name}: not a COCO instances file (no 'images' or 'annotations').")

    ds = Dataset(id=dataset_id_for(name, data), name=name, source_format=SourceFormat.COCO)
    ds.metadata["file"] = name
    info = doc.get("info")
    if isinstance(info, dict):
        ds.metadata["info"] = {k: str(v)[:200] for k, v in info.items()}

    for key in ("images", "annotations", "categories"):
        if not isinstance(doc.get(key, []), list):
            ds.parse_warnings.append(f"'{key}' is not a list and was ignored.")
            doc[key] = []
        if key not in doc:
            ds.parse_warnings.append(f"'{key}' is missing.")

    _parse_categories(doc.get("categories", []), ds)
    _parse_images(doc.get("images", []), ds)
    _parse_annotations(doc.get("annotations", []), ds)
    return ds


def _parse_categories(items: list[Any], ds: Dataset) -> None:
    ids = IdAllocator()
    for i, c in enumerate(items):
        if not isinstance(c, dict):
            ds.parse_warnings.append(f"categories[{i}] is not an object and was ignored.")
            continue
        source_id = str(c.get("id", ""))
        cid = ids.allocate(source_id)
        kps = c.get("keypoints") if isinstance(c.get("keypoints"), list) else []
        ds.categories.append(Category(id=cid, name=str(c.get("name", "")), keypoint_names=[str(k) for k in kps]))
        if cid != source_id:
            ds.metadata.setdefault("duplicate_category_ids", []).append(source_id)


def _parse_images(items: list[Any], ds: Dataset) -> None:
    ids = IdAllocator()
    for i, img in enumerate(items):
        if not isinstance(img, dict):
            ds.parse_warnings.append(f"images[{i}] is not an object and was ignored.")
            continue
        errors: list[str] = []
        source_id = str(img.get("id", f"#{i}"))
        if "id" not in img:
            errors.append("missing 'id'")
        image_id = ids.allocate(source_id)
        ds.images.append(
            ImageRecord(
                id=image_id,
                file_name=str(img.get("file_name", "")),
                width=to_float(img.get("width"), "width", errors),
                height=to_float(img.get("height"), "height", errors),
                source_location=f"images[{i}]",
                raw={"source_id": source_id, "parse_errors": errors},
            )
        )


def _pairs(flat: list[Any], label: str, errors: list[str]) -> list[list[float]]:
    if len(flat) % 2:
        errors.append(f"{label} has an odd number of values ({len(flat)})")
    return [
        [to_float(flat[j], f"{label}[{j}]", errors), to_float(flat[j + 1], f"{label}[{j + 1}]", errors)]
        for j in range(0, len(flat) - 1, 2)
    ]


def _parse_annotations(items: list[Any], ds: Dataset) -> None:
    ids = IdAllocator()
    cats = {c.id: c for c in ds.categories}
    for i, a in enumerate(items):
        loc = f"annotations[{i}]"
        if not isinstance(a, dict):
            ds.parse_warnings.append(f"{loc} is not an object and was ignored.")
            continue
        errors: list[str] = []
        source_id = str(a.get("id", f"#{i}"))
        for required in ("id", "image_id", "category_id"):
            if required not in a:
                errors.append(f"missing '{required}'")
        cat_id = str(a["category_id"]) if "category_id" in a else None
        cat = cats.get(cat_id) if cat_id is not None else None

        raw: dict[str, Any] = {"source_id": source_id}
        for k in ("area", "iscrowd", "num_keypoints"):
            if k in a:
                raw[k] = a[k]

        bbox = bbox_source = None
        if "bbox" in a:
            b = a["bbox"]
            if isinstance(b, list) and len(b) == 4:
                bbox_source = [to_float(v, f"bbox[{j}]", errors) for j, v in enumerate(b)]
                bbox = coco_to_xyxy(bbox_source)
            else:
                errors.append(f"'bbox' must be [x, y, width, height], got {str(b)[:60]}")
                bbox_source = [math.nan] * 4
                bbox = [math.nan] * 4

        polygons: list[list[list[float]]] = []
        seg = a.get("segmentation")
        if isinstance(seg, list):
            for p_idx, ring in enumerate(seg):
                if isinstance(ring, list):
                    polygons.append(_pairs(ring, f"segmentation[{p_idx}]", errors))
                else:
                    errors.append(f"segmentation[{p_idx}] is not a list")
        elif isinstance(seg, dict):
            raw["segmentation_rle"] = True

        points: list[list[float]] = []
        vis: list[int] = []
        kps = a.get("keypoints")
        if isinstance(kps, list) and kps:
            if len(kps) % 3:
                errors.append(f"'keypoints' length {len(kps)} is not a multiple of 3")
            for j in range(0, len(kps) - 2, 3):
                points.append(
                    [to_float(kps[j], f"keypoints[{j}]", errors), to_float(kps[j + 1], f"keypoints[{j + 1}]", errors)]
                )
                v = kps[j + 2]
                vis.append(int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else -1)
            if cat is not None:
                raw["keypoint_names"] = cat.keypoint_names

        if points:
            gtype = GeometryType.KEYPOINTS
        elif polygons:
            gtype = GeometryType.POLYGON
        elif bbox is not None:
            gtype = GeometryType.BBOX
        else:
            gtype = GeometryType.UNSUPPORTED
            raw["unsupported_shape"] = "rle_mask" if raw.get("segmentation_rle") else "no geometry"

        ds.annotations.append(
            Annotation(
                id=ids.allocate(source_id),
                image_id=str(a.get("image_id", "")),
                category=cat.name if cat else "",
                category_id=cat_id,
                geometry_type=gtype,
                bbox=bbox,
                bbox_source=bbox_source,
                polygons=polygons,
                points=points,
                keypoint_visibility=vis,
                attributes={str(k): str(v) for k, v in (a.get("attributes") or {}).items()}
                if isinstance(a.get("attributes"), dict)
                else {},
                source_format=SourceFormat.COCO,
                source_location=loc,
                parse_errors=errors,
                raw=raw,
            )
        )
